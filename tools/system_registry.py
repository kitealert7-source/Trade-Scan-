import json
import os
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone
import hashlib
from filelock import FileLock

# Ensure project root is importable when run as a script (python tools/system_registry.py).
# No-op when imported as a module from callers that already set sys.path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import (
    RUNS_DIR,
    REGISTRY_DIR,
    STRATEGIES_DIR,
    SELECTED_DIR,
    POOL_DIR,
    QUARANTINE_DIR,
    RUN_DIRS_IN_LOOKUP_ORDER,
)
from config.path_authority import TS_EXECUTION
from tools.event_log import log_event

PROJECT_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = REGISTRY_DIR / "run_registry.json"
LOCK_PATH = REGISTRY_PATH.with_suffix(".lock")

def _load_registry() -> dict:
    """Load run_registry.json with fail-hard semantics on corruption.

    Absence is a valid state (fresh install → empty dict). Corruption is not —
    silently degrading a corrupt registry to {} caused the FAKEBREAK P01/P02
    incident: downstream reconcilers saw every physical run as an orphan and
    queued legitimate directives for purge.
    """
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # Preserve forensic trail before raising.
        try:
            from tools.event_log import log_event
            log_event(
                action="INVARIANT_VIOLATION",
                target=f"file:{REGISTRY_PATH.name}",
                actor="_load_registry",
                reason="run_registry.json is corrupt",
                error=str(e),
                path=str(REGISTRY_PATH),
            )
        except Exception:
            pass
        raise RuntimeError(
            f"run_registry.json is present but not valid JSON: {REGISTRY_PATH}\n"
            f"  Error: {e}\n"
            f"Refusing to return an empty dict — silent empty-registry return "
            f"would cause downstream reconcilers to treat every physical run as "
            f"an orphan and may trigger catastrophic purges. Restore the file "
            f"from backup or fix manually before re-running."
        )
    except OSError as e:
        # Permission denied, I/O error, etc. — distinct from corruption.
        try:
            from tools.event_log import log_event
            log_event(
                action="INVARIANT_VIOLATION",
                target=f"file:{REGISTRY_PATH.name}",
                actor="_load_registry",
                reason="run_registry.json unreadable",
                error=str(e),
                path=str(REGISTRY_PATH),
            )
        except Exception:
            pass
        raise RuntimeError(
            f"run_registry.json exists but cannot be read: {REGISTRY_PATH}\n"
            f"  Error: {e}"
        )

def _save_registry_atomic(data: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    
    # Atomic rename (replace existing)
    if os.name == 'nt':
        if REGISTRY_PATH.exists():
            os.replace(tmp_path, REGISTRY_PATH)
        else:
            tmp_path.rename(REGISTRY_PATH)
    else:
        tmp_path.rename(REGISTRY_PATH)

def log_run_to_registry(run_id: str, status: str, directive_id: str):
    """
    Log a run into the master lifecycle ledger.
    Extracts the artifact_hash from the run_state.json if available.

    Write-time invariants (enforced at source instead of healed by reconciler):

      1. ``directive_id`` must be a non-empty string. Empty / None / whitespace
         linkage produces orphan registry entries that downstream reconcilers
         cannot repair without human investigation — fail hard at the source.

      2. The literal sentinel "recovered" is refused whenever ``run_state.json``
         carries a real ``directive_id``. The sentinel was the root cause of
         the 2026-04-09 FAKEBREAK P01/P02 incident: legitimate
         PORTFOLIO_COMPLETE directives were silently purged because their
         registry linkage had been corrupted to "recovered" while the real
         linkage still sat on disk. If the caller is trying to write the
         sentinel but reality contradicts it, reality wins.
    """
    # ---- Invariant 1: directive_id must be a non-empty string ----
    if not isinstance(directive_id, str) or not directive_id.strip():
        raise ValueError(
            f"log_run_to_registry: directive_id must be a non-empty string "
            f"(run_id={run_id!r}, got directive_id={directive_id!r})"
        )

    # Try to extract the computed artifact_hash AND the real directive_id from
    # run_state. Both are used below — artifact_hash for the registry entry,
    # state_directive_id for invariant 2.
    state_file = RUNS_DIR / run_id / "run_state.json"
    artifact_hash = None
    state_directive_id = None
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                artifact_hash = state_data.get("artifact_hash")
                state_directive_id = state_data.get("directive_id")
        except Exception:
            pass

    # ---- Invariant 2: refuse "recovered" sentinel when real ID is on disk ----
    if (
        directive_id == "recovered"
        and isinstance(state_directive_id, str)
        and state_directive_id.strip()
    ):
        print(
            f"[INVARIANT] log_run_to_registry: refusing 'recovered' sentinel "
            f"for run {run_id}; using real directive_id={state_directive_id} "
            f"from run_state.json."
        )
        log_event(
            action="INVARIANT_HEAL",
            target=f"run_id:{run_id}",
            actor="log_run_to_registry",
            reason="refused 'recovered' sentinel; used run_state.json directive_id",
            before={"directive_hash": "recovered"},
            after={"directive_hash": state_directive_id},
        )
        directive_id = state_directive_id

    with FileLock(str(LOCK_PATH)):
        reg = _load_registry()

        # If the run already exists, update status and possibly hash. Otherwise create new tier: sandbox.
        if status == "complete":
            # Verification Guard: Ensure core artifacts exist physically
            run_dir = RUNS_DIR / run_id
            required = [
                run_dir / "manifest.json",
                run_dir / "data" / "results_tradelevel.csv",
                run_dir / "data" / "results_standard.csv",
                run_dir / "data" / "equity_curve.csv"
            ]
            if not all(p.exists() for p in required):
                print(f"[INTEGRITY] Run {run_id} missing core artifacts. Downgrading status to 'failed'.")
                status = "failed"

        if run_id in reg:
            _prev_status = reg[run_id].get("status")
            _prev_directive = reg[run_id].get("directive_hash")
            reg[run_id]["status"] = status
            if artifact_hash and not reg[run_id].get("artifact_hash"):
                reg[run_id]["artifact_hash"] = artifact_hash
            # Back-heal: if the existing entry carries the "recovered" sentinel
            # and we now have a real directive_id, upgrade it. Symmetric to the
            # reconcile_registry() back-heal pass — keeps both write paths in
            # agreement so they cannot drift apart.
            if (
                reg[run_id].get("directive_hash") == "recovered"
                and directive_id != "recovered"
            ):
                print(
                    f"[INVARIANT] log_run_to_registry: healing 'recovered' "
                    f"sentinel on existing entry {run_id} -> directive={directive_id}."
                )
                log_event(
                    action="REGISTRY_DIRECTIVE_HEAL",
                    target=f"run_id:{run_id}",
                    actor="log_run_to_registry",
                    before={"directive_hash": "recovered"},
                    after={"directive_hash": directive_id},
                )
                reg[run_id]["directive_hash"] = directive_id
            log_event(
                action="REGISTRY_STATUS_CHANGE",
                target=f"run_id:{run_id}",
                actor="log_run_to_registry",
                before={"status": _prev_status},
                after={"status": status},
                directive_hash=reg[run_id].get("directive_hash"),
            )
        else:
            reg[run_id] = {
                "run_id": run_id,
                "tier": "sandbox",
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "directive_hash": directive_id,
                "artifact_hash": artifact_hash
            }
            log_event(
                action="REGISTRY_UPSERT",
                target=f"run_id:{run_id}",
                actor="log_run_to_registry",
                after={
                    "tier": "sandbox",
                    "status": status,
                    "directive_hash": directive_id,
                },
            )

        _save_registry_atomic(reg)

def get_active_portfolio_runs() -> set:
    """Collect the set of run_ids that back deployed strategies.

    Authority: portfolio.yaml is the sole deployment authority. The legacy
    DB ``IN_PORTFOLIO`` column has been retired along with this call site's
    dependency on it.

    Sources merged here:
      1. ``strategies/**/portfolio_composition.json`` (``constituent_run_ids``)
         — composite portfolios' constituent runs.
      2. ``portfolio.yaml`` ``portfolio.strategies[].run_id`` — every
         single-strategy deployment (LIVE, RETIRED, LEGACY, DISABLED).

    Failure policy: if portfolio.yaml exists but cannot be parsed, raise.
    A silent empty read would cause downstream reconcilers to treat every
    deployed run as an orphan (see FAKEBREAK P01/P02 incident). Absence is
    OK — a fresh install has no portfolio yet.
    """
    active_runs: set = set()

    # 1. Composite portfolio constituents.
    strategies_dir = STRATEGIES_DIR
    if strategies_dir.exists():
        for fname in ["portfolio_composition.json", "portfolio_metadata.json"]:
            for comp_file in strategies_dir.rglob(fname):
                try:
                    with open(comp_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    run_ids = data.get("constituent_run_ids", [])
                    if isinstance(run_ids, list):
                        active_runs.update(str(r) for r in run_ids if r)
                except Exception:
                    continue

    # 2. portfolio.yaml — authoritative deployment ledger.
    ts_exec_portfolio = TS_EXECUTION / "portfolio.yaml"
    if ts_exec_portfolio.exists():
        try:
            import yaml
            with open(ts_exec_portfolio, "r", encoding="utf-8") as f:
                ydata = yaml.safe_load(f) or {}
        except Exception as e:
            try:
                log_event(
                    action="INVARIANT_VIOLATION",
                    target="file:portfolio.yaml",
                    actor="get_active_portfolio_runs",
                    reason="portfolio.yaml is present but unparseable",
                    error=str(e),
                    path=str(ts_exec_portfolio),
                )
            except Exception:
                pass
            raise RuntimeError(
                f"portfolio.yaml is present but not valid YAML: "
                f"{ts_exec_portfolio}\n"
                f"  Error: {e}\n"
                f"Refusing to return a partial active-run set — silent empty "
                f"read would cause downstream reconcilers to treat every "
                f"deployed run as an orphan."
            )
        strategies = (ydata.get("portfolio") or {}).get("strategies") or []
        if isinstance(strategies, list):
            for entry in strategies:
                if not isinstance(entry, dict):
                    continue
                rid = entry.get("run_id")
                if isinstance(rid, str) and rid.strip():
                    active_runs.add(rid.strip())

    return active_runs

def reconcile_registry() -> dict:
    """
    Startup sweep to ensure consistency between registry and physical disk.
    - Physical folder but missing from registry -> inject as sandbox.
    - In registry but physical folder missing -> mark invalid.
    - Portfolio requires missing dependency -> hard crash.
    
    Returns:
        dict: Mismatch details for callers (e.g., gates).
    """
    runs_dir = RUNS_DIR

    results = {
        "orphaned_on_disk": [],
        "missing_from_disk": [],
        "invalid_in_registry": []
    }

    # 1. Physical vs Registry — iterate every canonical run directory.
    # Track each physical run's home directory so we can read its run_state.json
    # during recovery (required to preserve directive_id linkage).
    # Order is owned by config.state_paths.RUN_DIRS_IN_LOOKUP_ORDER — do not
    # duplicate it here. First-seen wins.
    physical_runs = set()
    physical_run_home: dict[str, Path] = {}
    for directory in RUN_DIRS_IN_LOOKUP_ORDER:
        if directory.exists():
            for item in directory.iterdir():
                if item.is_dir() and (item / "data").exists():
                    physical_runs.add(item.name)
                    physical_run_home.setdefault(item.name, item)

    def _recover_directive_hash(run_id: str) -> str:
        """Read run_state.json to recover the real directive_id.

        Falls back to the literal sentinel "recovered" only when run_state.json
        is missing, corrupt, or does not carry a directive_id. Keeping the real
        linkage is essential — `directive_reconciler.is_directive_living()`
        uses `directive_hash` to decide whether a .txt in completed/ is orphan
        garbage or an intact PORTFOLIO_COMPLETE directive. A blanket
        "recovered" sentinel breaks that contract and causes silent purges of
        legitimate directives on next --execute (see 41_REV_FX_*_FAKEBREAK
        P01/P02 incident, 2026-04-09).
        """
        home = physical_run_home.get(run_id)
        if home is None:
            return "recovered"
        state_file = home / "run_state.json"
        if not state_file.exists():
            # Check archived state files from prior resets — they still carry
            # the original directive_id.
            baks = sorted(home.glob("run_state.json.bak*"))
            if not baks:
                return "recovered"
            state_file = baks[-1]  # most recent archive
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            return "recovered"
        d_id = data.get("directive_id")
        if isinstance(d_id, str) and d_id.strip():
            return d_id
        return "recovered"

    # 2. Load registry, compute mutations, and save — all under lock to prevent TOCTOU race.
    #    Filesystem moves (step 3) happen outside the lock since they don't touch the registry file.
    with FileLock(str(LOCK_PATH)):
        reg = _load_registry()
        dirty = False

        # Missing from registry
        for phys_id in physical_runs:
            if phys_id not in reg:
                recovered_hash = _recover_directive_hash(phys_id)
                if recovered_hash == "recovered":
                    print(f"[RECONCILE] Recovered orphaned physical run {phys_id} -> sandbox (directive_id unknown).")
                else:
                    print(f"[RECONCILE] Recovered orphaned physical run {phys_id} -> sandbox (directive={recovered_hash}).")
                results["orphaned_on_disk"].append(phys_id)
                reg[phys_id] = {
                    "run_id": phys_id,
                    "tier": "sandbox",
                    "status": "complete", # Assume complete if it has a data folder
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "directive_hash": recovered_hash,
                    "artifact_hash": None
                }
                log_event(
                    action="REGISTRY_UPSERT",
                    target=f"run_id:{phys_id}",
                    actor="reconcile_registry",
                    reason="orphaned physical run injected as sandbox",
                    after={
                        "tier": "sandbox",
                        "status": "complete",
                        "directive_hash": recovered_hash,
                    },
                )
                dirty = True

        # Back-heal existing entries whose directive_hash is the legacy
        # "recovered" sentinel. If run_state.json now reveals the real
        # directive_id, upgrade the registry entry so downstream reconcilers
        # stop treating the run as an unlinked orphan.
        for run_id, data in reg.items():
            if data.get("directive_hash") != "recovered":
                continue
            if run_id not in physical_runs:
                continue
            real = _recover_directive_hash(run_id)
            if real != "recovered":
                print(f"[RECONCILE] Healed recovered-sentinel linkage: {run_id} -> directive={real}")
                log_event(
                    action="REGISTRY_DIRECTIVE_HEAL",
                    target=f"run_id:{run_id}",
                    actor="reconcile_registry",
                    before={"directive_hash": "recovered"},
                    after={"directive_hash": real},
                )
                data["directive_hash"] = real
                dirty = True

        # Build quarantine index once — runs intentionally archived by lifecycle cleanup.
        quarantine_runs_dir = QUARANTINE_DIR / "runs"
        quarantined_on_disk = set()
        if quarantine_runs_dir.exists():
            quarantined_on_disk = {p.name for p in quarantine_runs_dir.iterdir() if p.is_dir()}

        # Physically missing but in registry
        for run_id, data in list(reg.items()):
            if run_id not in physical_runs:
                current_status = data.get("status")

                # Run is in quarantine — intentionally archived, not broken.
                if run_id in quarantined_on_disk:
                    if current_status != "quarantined":
                        print(f"[RECONCILE] Registry entry {run_id} found in quarantine -> status corrected to quarantined.")
                        log_event(
                            action="REGISTRY_STATUS_CHANGE",
                            target=f"run_id:{run_id}",
                            actor="reconcile_registry",
                            reason="physical folder found in quarantine",
                            before={"status": current_status},
                            after={"status": "quarantined"},
                        )
                        reg[run_id]["status"] = "quarantined"
                        dirty = True
                    results["invalid_in_registry"].append(run_id)
                    continue

                if current_status in ("invalid", "quarantined"):
                    results["invalid_in_registry"].append(run_id)
                    continue

                if not (runs_dir / run_id).exists():
                    print(f"[RECONCILE] Registry entry {run_id} missing physical folder -> marked invalid.")
                    log_event(
                        action="RUN_INVALIDATE",
                        target=f"run_id:{run_id}",
                        actor="reconcile_registry",
                        reason="physical folder missing",
                        before={"status": current_status},
                        after={"status": "invalid"},
                    )
                    results["missing_from_disk"].append(run_id)
                    reg[run_id]["status"] = "invalid"
                    dirty = True
            else:
                # Run IS physically present but registry says invalid — stale flag, restore it.
                if data.get("status") == "invalid":
                    print(f"[RECONCILE] Run {run_id} is physically present but marked invalid -> restored to complete.")
                    log_event(
                        action="REGISTRY_STATUS_CHANGE",
                        target=f"run_id:{run_id}",
                        actor="reconcile_registry",
                        reason="stale invalid flag; physical folder present",
                        before={"status": "invalid"},
                        after={"status": "complete"},
                    )
                    reg[run_id]["status"] = "complete"
                    dirty = True

        # Commit — still under lock, load + mutate + save is now atomic
        if dirty:
            _save_registry_atomic(reg)

    # 3. Candidate Location Alignment (Auto-Repair) — filesystem moves, no registry lock needed
    for run_id, data in reg.items():
        if data.get("tier") == "candidate" and data.get("status") == "complete":
            src = RUNS_DIR / run_id
            dst = SELECTED_DIR / run_id
            if src.exists() and not dst.exists():
                print(f"[RECONCILE] Detected candidate {run_id} in sandbox. Auto-repairing physical location...")
                try:
                    SELECTED_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                except Exception as e:
                    print(f"[ERROR] Auto-repair migration failed for {run_id}: {e}")

    # AUTO-CLEAN: remove newly-invalid AND quarantined run_ids from portfolio_metadata.json files.
    # Quarantined runs are permanently absent — any portfolio reference to them is stale.
    newly_invalid = set(results["missing_from_disk"])
    quarantined_run_ids = {r for r, d in reg.items() if d.get("status") == "quarantined"}
    runs_to_purge_from_metadata = newly_invalid | quarantined_run_ids
    if runs_to_purge_from_metadata:
        newly_invalid = runs_to_purge_from_metadata  # reuse variable for block below
    if newly_invalid:
        for meta_file in STRATEGIES_DIR.rglob("portfolio_metadata.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                original = meta.get("constituent_run_ids", [])
                cleaned = [r for r in original if r not in newly_invalid]
                if len(cleaned) != len(original):
                    meta["constituent_run_ids"] = cleaned
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=4)
                    removed = set(original) - set(cleaned)
                    print(f"[RECONCILE] Auto-cleaned stale run_ids {removed} from {meta_file}")
            except Exception as e:
                print(f"[RECONCILE] Warning: could not clean {meta_file}: {e}")

    # 2. Portfolio Dependency Check
    # Runs with status "quarantined" are intentionally archived by the lifecycle cleanup.
    # They are permanently absent from runs/ but their portfolio data is already captured
    # in portfolio artifacts (tradelevel.csv, equity_curve.csv). Not a consistency violation.
    active_portfolio_runs = get_active_portfolio_runs()
    for dep_id in active_portfolio_runs:
        dep_status = reg.get(dep_id, {}).get("status")
        if dep_status == "quarantined":
            continue  # intentionally archived — portfolio data already captured
        if dep_id not in physical_runs or dep_status == "invalid":
            raise RuntimeError(f"[FATAL] Consistency Violation: Portfolio heavily depends on missing/invalid run {dep_id}.")
            
    print("[RECONCILE] Registry alignment complete.")
    return results


def _get_directive_first_execution_timestamp(directive_id: str):
    """
    Return the earliest run creation timestamp for a directive.

    Primary source: run_registry.json
      - Filter entries where directive_hash == directive_id
      - Parse created_at, return the minimum

    Fallback (registry missing / empty / no matching entries):
      - Scan RUNS_DIR for run_state.json files with matching directive_id
      - Extract timestamp with priority:
          a) history[0]['timestamp']  — definitively the run creation time
          b) last_updated             — set at initialization
          c) run_state.json mtime     — last resort
      - Return the minimum across all matching runs

    Returns None if no runs found → treated as new directive, reset allowed.
    All exceptions are caught safely; missing data is skipped, never crashes.
    """
    # --- PRIMARY: run_registry.json ---
    registry_ts = None
    if REGISTRY_PATH.exists():
        try:
            reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            for entry in reg.values():
                if entry.get("directive_hash") != directive_id:
                    continue
                raw = entry.get("created_at", "")
                if not raw:
                    continue
                try:
                    ts = datetime.fromisoformat(raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if registry_ts is None or ts < registry_ts:
                        registry_ts = ts
                except Exception:
                    continue
        except Exception:
            pass

    if registry_ts is not None:
        return registry_ts

    # --- FALLBACK: scan RUNS_DIR for run_state.json ---
    fallback_ts = None
    if not RUNS_DIR.exists():
        return None

    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        rs_file = run_dir / "run_state.json"
        if not rs_file.exists():
            continue
        try:
            rs = json.loads(rs_file.read_text(encoding="utf-8"))
            if rs.get("directive_id") != directive_id:
                continue

            ts = None

            # Priority a: first history entry timestamp (run creation)
            history = rs.get("history", [])
            if history:
                raw = history[0].get("timestamp", "")
                if raw:
                    try:
                        raw = raw.rstrip("Z")
                        if "+" not in raw:
                            raw += "+00:00"
                        ts = datetime.fromisoformat(raw)
                    except Exception:
                        pass

            # Priority b: last_updated (set at initialization)
            if ts is None:
                raw = rs.get("last_updated", "")
                if raw:
                    try:
                        raw = raw.rstrip("Z")
                        if "+" not in raw:
                            raw += "+00:00"
                        ts = datetime.fromisoformat(raw)
                    except Exception:
                        pass

            # Priority c: filesystem mtime of run_state.json
            if ts is None:
                ts = datetime.fromtimestamp(rs_file.stat().st_mtime, tz=timezone.utc)

            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if fallback_ts is None or ts < fallback_ts:
                    fallback_ts = ts

        except Exception:
            continue

    return fallback_ts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="System registry CLI — operator entry point for registry maintenance.")
    parser.add_argument("--reconcile", action="store_true",
                        help="Run reconcile_registry() — aligns registry with disk state (quarantine sync, "
                             "missing-on-disk resolution, portfolio_metadata auto-clean). Governance-audited.")
    args = parser.parse_args()

    if args.reconcile:
        reconcile_registry()
        print("[RECONCILE] Registry reconciliation complete")
    else:
        parser.print_help()
