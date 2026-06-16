import os
import sys
import shutil
import datetime
import json
import argparse
import yaml
import pandas as pd
from pathlib import Path

# Paths to core state repositories
PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys as _sys
if str(PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(PROJECT_ROOT))
from config.path_authority import TRADE_SCAN_STATE as STATE_ROOT, TS_EXECUTION as _TS_EXECUTION

MASTER_SHEET_PATH = STATE_ROOT / "strategies" / "Master_Portfolio_Sheet.xlsx"
FILTERED_SHEET_PATH = STATE_ROOT / "candidates" / "Filtered_Strategies_Passed.xlsx"

DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives"
RUNS_DIR = STATE_ROOT / "runs"
BACKTESTS_DIR = STATE_ROOT / "backtests"
STRATEGIES_DIR = STATE_ROOT / "strategies"
DEPLOYED_STRATEGIES_DIR = PROJECT_ROOT / "strategies"
SANDBOX_DIR = STATE_ROOT / "sandbox"
QUARANTINE_DIR = STATE_ROOT / "quarantine"
REGISTRY_PATH = STATE_ROOT / "registry" / "run_registry.json"

# Sidecar markers appended to <id>.txt that share the directive's lifecycle —
# orphaning them in completed/ produces the false appearance of "truncated"
# directives. Adding a new entry here plumbs the suffix through the scan and
# the quarantine move automatically.
DIRECTIVE_SIDECAR_SUFFIXES = (".admitted",)

# Directive IDs registered as pytest fixtures. These .txt files live under
# backtest_directives/completed/ but back NO real pipeline state — they are
# the canonical on-disk shape that broader pytest suites parse. The mechanism
# parallels tools/directive_reconciler.py's 4th living-signal; the
# pipeline-state-cleanup engine MUST honor the same registry or a cleanup
# sweep silently re-quarantines them. 2026-05-22 incident: this exact path
# quarantined 90_PORT_H2_5M_RECYCLE_S01_V1_P00 — already protected for
# directive_reconciler by cad47a0 but NOT here — re-breaking 12 broader-pytest
# tests across the basket suite (an un-ported-mechanism regression).
FIXTURE_REGISTRY_PATH = PROJECT_ROOT / "tests" / "_fixtures" / "directives.yaml"


def _load_fixture_directives() -> frozenset:
    """Return the set of directive_ids protected as test fixtures.

    Mirrors tools/directive_reconciler._load_fixture_directives. Fail-soft:
    a missing or malformed YAML yields an empty set so a cleanup run is never
    blocked by test-infrastructure drift.
    """
    if not FIXTURE_REGISTRY_PATH.exists():
        return frozenset()
    try:
        payload = yaml.safe_load(FIXTURE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Failed to read fixture registry {FIXTURE_REGISTRY_PATH}: {exc}")
        return frozenset()
    ids = payload.get("protected_directives") if isinstance(payload, dict) else None
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(str(i) for i in ids if isinstance(i, str))


def execution_pid_exists() -> bool:
    """Returns True if TS_Execution appears to be running.

    Two-layer check:
      1. PID file — if the recorded PID is alive, definitely running.
      2. Heartbeat file — if modified within last 5 minutes, treat as running
         even if PID file is stale (process may have been re-launched with a
         new PID without updating the old file).
    """
    import time
    ts_exec_logs = _TS_EXECUTION / "outputs" / "logs"

    # Layer 1: PID file
    pid_path = ts_exec_logs / "execution.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            print("[BLOCK] execution.pid is corrupt")
            sys.exit(1)
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                # Verify the process is actually Python (not a recycled PID)
                is_python = True  # default: assume alive if name check fails
                try:
                    try:
                        import psutil
                        proc = psutil.Process(pid)
                        proc_name = proc.exe().lower()
                        if "python" not in proc_name:
                            is_python = False
                            print(f"[WARN] PID {pid} is alive but not a Python process (image: {proc_name}). Treating as stale/recycled PID.")
                    except ImportError:
                        # psutil not available — use ctypes QueryFullProcessImageNameA
                        buf = ctypes.create_string_buffer(1024)
                        buf_size = ctypes.c_uint32(1024)
                        success = kernel32.QueryFullProcessImageNameA(handle, 0, buf, ctypes.byref(buf_size))
                        if success:
                            proc_name = buf.value.decode("utf-8", errors="replace").lower()
                            if "python" not in proc_name:
                                is_python = False
                                print(f"[WARN] PID {pid} is alive but not a Python process (image: {proc_name}). Treating as stale/recycled PID.")
                except Exception:
                    pass  # name check failed — fall back to assuming alive
                kernel32.CloseHandle(handle)
                if is_python:
                    return True
                # Not a Python process — fall through to heartbeat check
            else:
                # PID is dead on Windows — clean up stale PID file
                try:
                    pid_path.unlink()
                    print(f"[INFO] Cleaned stale execution.pid (PID {pid} is no longer running)")
                except OSError:
                    pass
        else:
            try:
                os.kill(pid, 0)
                return True
            except PermissionError:
                return True
            except OSError:
                # PID is dead on Linux — clean up stale PID file
                try:
                    pid_path.unlink()
                    print(f"[INFO] Cleaned stale execution.pid (PID {pid} is no longer running)")
                except OSError:
                    pass

    # Layer 2: Heartbeat freshness (catches stale PID + re-launched process)
    hb_path = ts_exec_logs / "heartbeat.log"
    if hb_path.exists():
        age_seconds = time.time() - hb_path.stat().st_mtime
        if age_seconds < 300:  # 5 minutes
            return True

    return False


def build_execution_shield(allow_empty: bool = False) -> set:
    """
    Returns the set of strategy IDs currently deployed in TS_Execution/portfolio.yaml.

    This is an ADDITIVE shield on top of the ledger-sourced keep-set (build_keep_runs:
    FSP / MPS / cointegration_sheet is_current=1 / PORTFOLIO_COMPLETE), NOT the keep-set
    itself. A MISSING or MALFORMED portfolio.yaml is always fatal — the shield cannot be
    confirmed, so pruning is unsafe. An EMPTY-but-valid portfolio (a deliberately
    stood-down fleet, 0 LIVE) is a VALID state, not a corruption: with allow_empty=True it
    yields an empty shield (nothing deployed -> nothing to shield), letting keep-set-driven
    corpus pruning run on an idle fleet. Default (allow_empty=False) keeps the empty case a
    hard BLOCK so nothing changes for the normal live-fleet path.
    """
    portfolio_path = _TS_EXECUTION / "portfolio.yaml"
    if not portfolio_path.exists():
        print("[BLOCK] portfolio.yaml not found or invalid")
        sys.exit(1)
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        strategies = data.get("portfolio", {}).get("strategies", []) or []
        if not strategies:
            if allow_empty:
                print("[WARN] portfolio.yaml is empty (stood-down fleet, 0 LIVE); "
                      "proceeding with an EMPTY execution shield (--allow-empty-shield). "
                      "Keep-set protection is unchanged (ledger-sourced).")
                return set()
            print("[BLOCK] portfolio.yaml parsed but no strategies found")
            sys.exit(1)
        return {
            s["id"]
            for s in strategies
            if s.get("enabled", False) and s.get("id")
        }
    except Exception:
        print("[BLOCK] portfolio.yaml not found or invalid")
        sys.exit(1)


def _collect_portfolio_complete_runs() -> tuple[set, set]:
    """Scan directive_state.json files for protected/PORTFOLIO_COMPLETE directives.

    Checks two signals (either triggers protection):
    1. Explicit ``protected: true`` flag (set by FSM on PORTFOLIO_COMPLETE transition)
    2. Latest attempt status == PORTFOLIO_COMPLETE (implicit scan, backward compat)

    Returns (run_ids, directive_ids) for all protected directives.
    """
    protected_runs = set()
    protected_directives = set()
    if not RUNS_DIR.exists():
        return protected_runs, protected_directives
    for d in RUNS_DIR.iterdir():
        ds = d / "directive_state.json"
        if not ds.exists():
            continue
        try:
            data = json.loads(ds.read_text(encoding="utf-8"))
            # Signal 1: explicit protection flag
            is_protected = data.get("protected", False)
            # Signal 2: PORTFOLIO_COMPLETE status (backward compat)
            latest = data.get("latest_attempt", "attempt_01")
            attempt = data.get("attempts", {}).get(latest, {})
            is_complete = attempt.get("status") == "PORTFOLIO_COMPLETE"
            if is_protected or is_complete:
                protected_directives.add(d.name)
                for rid in attempt.get("run_ids", []):
                    protected_runs.add(rid)
        except Exception:
            continue
    return protected_runs, protected_directives


def _row_is_quarantined(row, *, bool_col: str | None = None, status_col: str | None = None) -> bool:
    """Return True if a ledger row is tagged to skip referential checks.

    Rows tagged this way are honored as "intentionally orphaned" by past
    cleanups — the lineage they reference is no longer expected on disk.
    Two conventions in use:
      * FSP: boolean `quarantined` column (True/False).
      * MPS Portfolios + SAC: `quarantine_status` column set to any non-null
        string (ARCHIVED_DEPENDENCY_LOST, SUPERSEDED, ARCHIVED_UNRESOLVED, ...).
    """
    if bool_col and bool_col in row.index:
        v = row[bool_col]
        if isinstance(v, bool) and v:
            return True
        s = str(v).strip().lower()
        if s in ("true", "1", "yes"):
            return True
    if status_col and status_col in row.index:
        v = row[status_col]
        if v is None:
            return False
        s = str(v).strip()
        if s and s.lower() not in ("nan", "none", ""):
            return True
    return False


def _cointegration_keep_info() -> dict[str, tuple[str, str]]:
    """Current cointegration_sheet run_ids -> (directive_id, basket_id).

    DB-sourced: the xlsx Cointegration tab is a projected human view that drops
    run_id/directive_id, so the keep-set must read the source-of-truth DB. The
    "COINT TRADE CANDIDATES" tab is a further pair-grain render of the same
    table — also a projection, not independently pruned (covered via the DB).
    basket_id is recovered from the backtests_path basename (the run folder is
    "<directive_id>_<basket_id>"). Cointegration runs live in
    backtests/<directive_id>_<basket_id>/ like baskets, so they get the same
    backtests-aware integrity treatment. Empty on any error / absent table.
    """
    info: dict[str, tuple[str, str]] = {}
    try:
        from tools.ledger_db import _connect
        conn = _connect()
        try:
            has = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='cointegration_sheet'"
            ).fetchone()
            if not has:
                return info
            rows = conn.execute(
                "SELECT run_id, directive_id, backtests_path FROM cointegration_sheet "
                "WHERE is_current = 1"
            ).fetchall()
        finally:
            conn.close()
        for rid, did, btp in rows:
            rid = str(rid or "").strip()
            if not rid:
                continue
            did = str(did or "").strip()
            folder = Path(str(btp or "")).name
            bid = folder[len(did) + 1:] if folder.startswith(did + "_") else ""
            info[rid] = (did, bid)
    except Exception as exc:
        print(f"[INFO] Cointegration keep-set skipped: {exc}")
    return info


def build_keep_runs() -> tuple[set, set, dict]:
    """Build union index from candidates and active portfolio subsets.

    Rows tagged `quarantined=True` (FSP) or `quarantine_status` set (MPS
    Portfolios / Single-Asset Composites / Baskets) are skipped — they declare
    that the referenced run_ids are NOT expected to exist on disk, which is the
    operator-honored way to record dependency loss without violating the
    append-only invariant.

    Returns (keep_runs, active_portfolios, basket_run_info) where
    basket_run_info maps basket run_id -> (directive_id, basket_id) so the
    integrity check can do basket-aware disk validation. Basket runs canonically
    keep their research artifacts in backtests/<directive_id>_<basket_id>/
    rather than runs/<run_id>/, so the standard run_dir+JSON check is too strict.
    """
    keep_runs = set()
    active_portfolios = set()
    basket_run_info: dict[str, tuple[str, str]] = {}

    # 1. Extract from Filtered_Strategies_Passed (skip quarantined rows)
    if not FILTERED_SHEET_PATH.exists():
        print(f"[FAIL] Missing {FILTERED_SHEET_PATH}")
        sys.exit(1)

    df_filtered = pd.read_excel(FILTERED_SHEET_PATH)
    for _, row in df_filtered.iterrows():
        if _row_is_quarantined(row, bool_col="quarantined"):
            continue
        r_str = str(row.get("run_id", "")).strip()
        if r_str and r_str.lower() != "nan":
            keep_runs.add(r_str)

    # 2. Extract from Master_Portfolio_Sheet (Portfolios + SAC sheets,
    #    skip rows tagged with quarantine_status).
    if not MASTER_SHEET_PATH.exists():
        print(f"[FAIL] Missing {MASTER_SHEET_PATH}")
        sys.exit(1)

    for sheet_name in ("Portfolios", "Single-Asset Composites"):
        try:
            df_sheet = pd.read_excel(MASTER_SHEET_PATH, sheet_name=sheet_name)
        except (ValueError, KeyError):
            continue
        for _, row in df_sheet.iterrows():
            if _row_is_quarantined(row, status_col="quarantine_status"):
                continue
            port_id = str(row.get("portfolio_id", "")).strip()
            constituents = str(row.get("constituent_run_ids", "")).strip()
            if port_id and port_id.lower() != "nan":
                active_portfolios.add(port_id)
                if constituents and constituents.lower() != "nan":
                    for r_id in constituents.split(","):
                        p_str = r_id.strip()
                        if p_str:
                            keep_runs.add(p_str)

    # 2b. Extract from Master_Portfolio_Sheet::Baskets (added 2026-05-27 — Baskets
    #     is now a first-class managed sheet; matches repair_integrity.py's
    #     scan_baskets extension. Single run_id per row, no constituent_run_ids.
    #     Without this, the pruner treats basket disk as abandoned every run.
    #     Also records (directive_id, basket_id) per run so the integrity
    #     check can do basket-aware disk validation (backtest-dir is enough
    #     even when runs/<run_id>/ is gone).
    try:
        df_baskets = pd.read_excel(MASTER_SHEET_PATH, sheet_name="Baskets")
        for _, row in df_baskets.iterrows():
            if _row_is_quarantined(row, status_col="quarantine_status"):
                continue
            rid = str(row.get("run_id", "")).strip()
            if rid and rid.lower() != "nan":
                keep_runs.add(rid)
                did = str(row.get("directive_id", "")).strip()
                bid = str(row.get("basket_id", "")).strip()
                basket_run_info[rid] = (did, bid)
    except (ValueError, KeyError):
        pass

    # 2c. Cointegration ledger (DB-sourced; the xlsx tab is a projected view
    #     that drops run_id/directive_id). Coint runs live in
    #     backtests/<directive_id>_<basket_id>/ like baskets, so add them to
    #     keep_runs and record (directive_id, basket_id) for backtests-aware
    #     integrity. Without this, a future cleanup prunes coint substrate.
    for _crid, _cdibi in _cointegration_keep_info().items():
        keep_runs.add(_crid)
        basket_run_info[_crid] = _cdibi

    # 3. Protect PORTFOLIO_COMPLETE directives (promotion-eligible, not yet in spreadsheets)
    pc_runs, pc_directives = _collect_portfolio_complete_runs()
    pre_count = len(keep_runs)
    keep_runs |= pc_runs
    added = len(keep_runs) - pre_count
    if added > 0:
        print(f"[INFO] Protected {added} additional run(s) from {len(pc_directives)} PORTFOLIO_COMPLETE directive(s)")

    return keep_runs, active_portfolios, basket_run_info


def verify_referential_integrity(keep_runs: set, active_portfolios: set,
                                  basket_run_info: dict | None = None):
    """Enforce absolute referential safety invariants before mutation checks.

    Baskets get a relaxed check: the basket-canonical artifact is the per-bar
    parquet at backtests/<directive_id>_<basket_id>/raw/results_basket_per_bar.parquet,
    not runs/<run_id>/run_state.json. A basket row is valid if it has EITHER
    the standard run_dir+JSON pair OR the basket backtest dir present.
    """
    print("--- Phase 1B: Referential Integrity Check ---")

    if basket_run_info is None:
        basket_run_info = {}

    missing_critical = []

    # Check 1: Verify valid state dimensions
    total_keep = len(keep_runs)
    runs_count = len([d for d in RUNS_DIR.iterdir() if d.is_dir()]) if RUNS_DIR.exists() else 0
    sandbox_count = len([d for d in SANDBOX_DIR.iterdir() if d.is_dir()]) if SANDBOX_DIR.exists() else 0
    # sandbox/ is a valid run home — the per-run check below accepts it, so include both tiers in the global tally.
    total_disk_runs = runs_count + sandbox_count

    # Mathematical sanity bound checking against total disk vs targets.
    # Subtract basket runs from total_keep — they may live in backtests/ only,
    # which doesn't count toward the runs/+sandbox/ tally but is still valid.
    non_basket_keep = total_keep - len(basket_run_info)
    if total_disk_runs < non_basket_keep:
        print(f"[FAIL] Integrity breached: Total disk runs ({total_disk_runs} = {runs_count} runs/ + {sandbox_count} sandbox/) is less than required non-basket targets ({non_basket_keep}).")
        sys.exit(1)

    # Check 2 & 3: Deep check file linkages
    for r_id in keep_runs:
        target_run = RUNS_DIR / r_id
        target_sandbox = SANDBOX_DIR / r_id
        target_json = BACKTESTS_DIR / f"{r_id}.json"
        sandbox_state = target_sandbox / "run_state.json"
        run_state = target_run / "run_state.json"

        has_run = target_run.exists() and target_run.is_dir()
        has_sandbox = target_sandbox.exists() and target_sandbox.is_dir()
        has_json = target_json.exists() or sandbox_state.exists() or run_state.exists()

        # Standard run+JSON pair is valid for any run (basket or not).
        if (has_run or has_sandbox) and has_json:
            continue

        # Basket fallback: accept basket backtest dir as proof of validity.
        if r_id in basket_run_info:
            did, bid = basket_run_info[r_id]
            if did and bid:
                bt_parquet = BACKTESTS_DIR / f"{did}_{bid}" / "raw" / "results_basket_per_bar.parquet"
                if bt_parquet.exists():
                    continue
            missing_critical.append(
                f"Missing basket disk (no runs/{r_id}/ AND no backtests/{did}_{bid}/raw/results_basket_per_bar.parquet)"
            )
            continue

        # Standard (non-basket) failure reporting.
        if not has_run and not has_sandbox:
            missing_critical.append(f"Missing native run folder in both runs/ and sandbox/: {r_id}")
        if not has_json:
            missing_critical.append(f"Missing backtest JSON artifact for: {r_id}")

    # Check 4: Portfolio Folder matching
    for p_id in active_portfolios:
        target_port = STRATEGIES_DIR / p_id
        if not target_port.exists() or not target_port.is_dir():
            missing_critical.append(f"Missing deployed portfolio folder: {target_port}")

    if len(missing_critical) > 0:
        print("[FAIL] REFERENTIAL INTEGRITY BREACHED. Missing dependencies detected:")
        for m in missing_critical[:10]:
            print(f"  -> {m}")
        if len(missing_critical) > 10:
            print(f"  ... and {len(missing_critical)-10} more.")
        sys.exit(1)
        
    print(f"[PASS] Exact referential integrity validated for {total_keep} base runs and {len(active_portfolios)} portfolios.")


def _collect_directive_targets(directives_dir: Path, keep_runs: set) -> list:
    """Return unmapped directive .txt files paired with their sidecar markers.

    Each <id>.txt outside keep_runs is followed by every existing
    <id>.txt<suffix> sentinel listed in DIRECTIVE_SIDECAR_SUFFIXES, so the
    quarantine sweep moves them atomically.

    Directive IDs registered in tests/_fixtures/directives.yaml are skipped
    regardless of keep_runs linkage — they are pytest fixtures that back no
    pipeline state but must remain on disk (parallels directive_reconciler's
    4th living-signal; see _load_fixture_directives).
    """
    protected_fixtures = _load_fixture_directives()
    out: list = []
    for d in directives_dir.rglob("*.txt"):
        if not d.is_file():
            continue
        if d.stem in keep_runs:
            continue
        if d.stem in protected_fixtures:
            continue
        out.append(d)
        for suffix in DIRECTIVE_SIDECAR_SUFFIXES:
            sidecar = d.with_name(d.name + suffix)
            if sidecar.exists():
                out.append(sidecar)
    return out


def scan_and_map(keep_runs: set, active_portfolios: set, allow_empty_shield: bool = False) -> dict:
    """Map the filesystem strictly to identify quaratine candidates."""
    execution_set = build_execution_shield(allow_empty=allow_empty_shield)

    # Build broader folder protection set:
    #   - Master_Portfolio_Sheet portfolio_ids (active_portfolios)
    #   - Filtered_Strategies_Passed strategy names
    #   - portfolio.yaml deployed strategy IDs (execution_set)
    #   - PORTFOLIO_COMPLETE directive IDs (promotion-eligible)
    protected_folders = set(active_portfolios)
    protected_folders |= execution_set
    _, pc_directives = _collect_portfolio_complete_runs()
    protected_folders |= pc_directives
    filt_strats = set()
    if FILTERED_SHEET_PATH.exists():
        df_filt = pd.read_excel(FILTERED_SHEET_PATH)
        for s in df_filt.get("strategy", []):
            s_str = str(s).strip()
            if s_str and s_str.lower() != "nan":
                filt_strats.add(s_str)
                protected_folders.add(s_str)

    print(f"[INFO] Protected folders: {len(protected_folders)} (Master={len(active_portfolios)}, Filtered={len(filt_strats)}, Execution={len(execution_set)})")

    targets = {
        "runs": [],
        "backtests": [],
        "directives": [],
        "portfolios": [],
        "deployed_portfolios": [],
        "sandbox": []
    }

    # 1. Scan Runs Directory
    for f in RUNS_DIR.iterdir():
        if f.is_dir():
            # Exact identity check required.
            if f.name not in keep_runs:
                targets["runs"].append(f)

    # 2. Scan Backtests Directory
    for f in BACKTESTS_DIR.glob("*.json"):
        if f.is_file():
            # Stripping precisely the .json suffix
            file_id = f.stem
            if file_id not in keep_runs:
                targets["backtests"].append(f)

    # 3. Scan Directives Directory
    targets["directives"].extend(_collect_directive_targets(DIRECTIVES_DIR, keep_runs))

    # 4. Scan Portfolios
    for f in STRATEGIES_DIR.iterdir():
        if f.is_dir():
            # Explicit bypass list
            if f.name in ["Master_Portfolio_Sheet.xlsx", "Master_Portfolio_Sheet", "master", "sandbox", "candidates", "evaluations", "Master_Portfolios"]: 
                continue
            
            # The sandbox is actually handled elsewhere, but in case there are other subfolders:
            if f.name not in protected_folders:
                targets["portfolios"].append(f)

    # 5. Scan Local App Deployments
    if DEPLOYED_STRATEGIES_DIR.exists():
        for f in DEPLOYED_STRATEGIES_DIR.iterdir():
            if f.is_dir() and f.name not in ["_deployments"]:
                if f.name not in protected_folders:
                    targets["deployed_portfolios"].append(f)

    # 6. Scan Sandbox cache layer
    if SANDBOX_DIR.exists():
        for f in SANDBOX_DIR.iterdir():
            if f.is_dir() and f.name not in keep_runs:
                targets["sandbox"].append(f)

    relevant = targets["portfolios"] + targets["deployed_portfolios"]
    to_quarantine = [p.name for p in relevant]
    conflicts = [x for x in to_quarantine if x in execution_set]
    if conflicts:
        print("[BLOCK] Attempted to quarantine deployed strategies:")
        for c in conflicts:
            print(f"  - {c}")
        sys.exit(1)

    return targets


def dry_run_simulation(keep_runs: set, active_portfolios: set, targets: dict):
    print("\n--- Phase 3: Dry Run & Validation ---")
    
    t_runs = len(targets["runs"])
    t_json = len(targets["backtests"])
    t_port = len(targets["portfolios"])
    t_dir = len(targets["directives"])
    
    print("\n[Sanity Check Tally]")
    print(f"Total KEEP_RUNS exact map:    {len(keep_runs)}")
    disk_runs = len([d for d in RUNS_DIR.iterdir() if d.is_dir()]) if RUNS_DIR.exists() else 0
    print(f"Total physical runs on disk:  {disk_runs}")
    
    print("\n[Grouped Counts For Deletion/Quarantine]")
    print(f"Runs to delete:        {t_runs}")
    print(f"Backtests to delete:   {t_json}")
    print(f"Directives to delete:  {t_dir}")
    print(f"Portfolios to delete:  {t_port}")
    print(f"Local App Ports to delete: {len(targets['deployed_portfolios'])}")
    print(f"Sandbox cache to delete:   {len(targets['sandbox'])}")
    
    # Explicit Safety Flag Test
    # "no KEEP_RUNS ID appears anywhere in the delete list"
    safety_breach = False
    for path in targets["runs"]:
        if path.name in keep_runs:
            print(f"[URGENT FAIL] Invariant Breach: {path.name} marked for deletion but mapped in KEEP_RUNS!")
            safety_breach = True
            
    for path in targets["backtests"]:
        if path.stem in keep_runs:
            print(f"[URGENT FAIL] Invariant Breach: {path.stem} marked for deletion but mapped in KEEP_RUNS!")
            safety_breach = True

    if safety_breach:
        sys.exit(1)
    
    print("\n[PASS] No KEEP_RUNS ID appears in delete list.")


def batch_update_registry_status(run_ids: list, new_status: str):
    """Batch-update status field in run_registry.json for multiple run_ids.

    Single load → N mutations in memory → single atomic write.

    Safety rules:
      - run_ids not in registry are silently skipped (no new entries created).
      - Only modifies the 'status' field. All other fields are untouched.
      - Atomic write: tmp file + os.replace to prevent partial writes on crash.
    """
    if not REGISTRY_PATH.exists() or not run_ids:
        return
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        changed = 0
        for rid in run_ids:
            if rid in reg:
                reg[rid]["status"] = new_status
                changed += 1
        if changed == 0:
            return
        tmp_path = REGISTRY_PATH.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(REGISTRY_PATH))
        print(f"  -> Registry: {changed} entries marked '{new_status}'")
    except Exception as e:
        print(f"[WARN] Registry batch update failed: {e}")


def execute_purge(targets: dict):
    print("\n--- Phase 4: Execution (Quarantine Migration) ---")
    
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sandbox_dir = QUARANTINE_DIR / f"{ts}_cleanup"
    sandbox_dir.mkdir(exist_ok=True)
    counts = {k: 0 for k in targets.keys()}
    quarantined_run_ids = []
    for category, path_list in targets.items():
        cat_dir = sandbox_dir / category
        cat_dir.mkdir(exist_ok=True)

        for p in path_list:
            try:
                # Hard strict OS move
                shutil.move(str(p), str(cat_dir / p.name))
                counts[category] += 1
                if category in ("runs", "sandbox"):
                    quarantined_run_ids.append(p.name)
            except Exception as e:
                print(f"[WARN] Failed to move {p.name}: {e}")

    print(f"[SUCCESS] Migrated {sum(counts.values())} artifacts to {sandbox_dir.name}")

    # Batch registry sync — single atomic write after all moves complete
    if quarantined_run_ids:
        batch_update_registry_status(quarantined_run_ids, "quarantined")
    
    # Emitting reporting output
    report_data = {
        "timestamp": ts,
        "runs_before": sum(counts.values()) + len(targets.get("runs", [])),  # Rough calculation
        "deleted_counts": counts,
        "mode": "EXECUTE"
    }
    
    log_dir = STATE_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "cleanup_report.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=4)
    print(f"  -> Dumped summary to {log_dir / 'cleanup_report.json'}")


def main():
    parser = argparse.ArgumentParser(description="State Lifecycle Lineage Pruner")
    parser.add_argument("--execute", action="store_true", help="Acknowledge destructive move and bypass dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run (default behaviour — no mutations). Mutually exclusive with --execute.")
    parser.add_argument("--force-unlock", action="store_true", help="Bypass TS_Execution safety check. Use only when certain TS_Execution is not running.")
    parser.add_argument("--allow-empty-shield", action="store_true", help="Permit an empty (stood-down, 0-LIVE) portfolio.yaml to yield an empty execution shield instead of blocking, so keep-set-driven corpus pruning can run on an idle fleet. Keep-set is ledger-sourced; a MISSING/malformed portfolio.yaml still blocks.")
    args = parser.parse_args()

    if args.dry_run and args.execute:
        print("[ERROR] --dry-run and --execute are mutually exclusive.")
        sys.exit(2)

    if args.force_unlock:
        print("[WARN] --force-unlock: Bypassing TS_Execution safety check. Use only when you are certain TS_Execution is not running.")
    elif execution_pid_exists():
        print("[BLOCK] TS_Execution is running")
        sys.exit(1)

    keep_runs, active_portfolios, basket_run_info = build_keep_runs()

    verify_referential_integrity(keep_runs, active_portfolios, basket_run_info)
    
    targets = scan_and_map(keep_runs, active_portfolios, allow_empty_shield=args.allow_empty_shield)
    
    dry_run_simulation(keep_runs, active_portfolios, targets)
    
    if args.execute:
        execute_purge(targets)
    else:
        print("\n[HALT] Executed cleanly in DRY_RUN mode. Use --execute to structurally quarantine items.")
        print("[DRY-RUN] No changes applied")


if __name__ == "__main__":
    main()
