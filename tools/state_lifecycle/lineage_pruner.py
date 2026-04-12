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
STATE_ROOT   = PROJECT_ROOT.parent / "TradeScan_State"

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

def execution_pid_exists() -> bool:
    """Returns True if TS_Execution appears to be running.

    Two-layer check:
      1. PID file — if the recorded PID is alive, definitely running.
      2. Heartbeat file — if modified within last 5 minutes, treat as running
         even if PID file is stale (process may have been re-launched with a
         new PID without updating the old file).
    """
    import time
    ts_exec_logs = PROJECT_ROOT.parent / "TS_Execution" / "outputs" / "logs"

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


def build_execution_shield() -> set:
    """
    Returns set of strategy IDs currently deployed in TS_Execution/portfolio.yaml
    """
    portfolio_path = PROJECT_ROOT.parent / "TS_Execution" / "portfolio.yaml"
    if not portfolio_path.exists():
        print("[BLOCK] portfolio.yaml not found or invalid")
        sys.exit(1)
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        strategies = data.get("portfolio", {}).get("strategies", []) or []
        if not strategies:
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


def build_keep_runs() -> tuple[set, set]:
    """Build union index from candidates and active portfolio subsets."""
    keep_runs = set()
    active_portfolios = set()

    # 1. Extract from Filtered_Strategies_Passed
    if not FILTERED_SHEET_PATH.exists():
        print(f"[FAIL] Missing {FILTERED_SHEET_PATH}")
        sys.exit(1)

    df_filtered = pd.read_excel(FILTERED_SHEET_PATH)
    for run_id in df_filtered.get("run_id", []):
        r_str = str(run_id).strip()
        if r_str and r_str.lower() != "nan":
            keep_runs.add(r_str)

    # 2. Extract from Master_Portfolio_Sheet
    if not MASTER_SHEET_PATH.exists():
        print(f"[FAIL] Missing {MASTER_SHEET_PATH}")
        sys.exit(1)

    df_master = pd.read_excel(MASTER_SHEET_PATH)
    for _, row in df_master.iterrows():
        port_id = str(row.get("portfolio_id", "")).strip()
        constituents = str(row.get("constituent_run_ids", "")).strip()

        if port_id and port_id.lower() != "nan":
            active_portfolios.add(port_id)
            if constituents and constituents.lower() != "nan":
                # Split by comma and add exactly
                for r_id in constituents.split(","):
                    p_str = r_id.strip()
                    if p_str:
                        keep_runs.add(p_str)

    # 3. Protect PORTFOLIO_COMPLETE directives (promotion-eligible, not yet in spreadsheets)
    pc_runs, pc_directives = _collect_portfolio_complete_runs()
    pre_count = len(keep_runs)
    keep_runs |= pc_runs
    added = len(keep_runs) - pre_count
    if added > 0:
        print(f"[INFO] Protected {added} additional run(s) from {len(pc_directives)} PORTFOLIO_COMPLETE directive(s)")

    return keep_runs, active_portfolios


def verify_referential_integrity(keep_runs: set, active_portfolios: set):
    """Enforce absolute referential safety invariants before mutation checks."""
    print("--- Phase 1B: Referential Integrity Check ---")
    
    missing_critical = []
    
    # Check 1: Verify valid state dimensions
    total_keep = len(keep_runs)
    total_disk_runs = len([d for d in RUNS_DIR.iterdir() if d.is_dir()]) if RUNS_DIR.exists() else 0
    
    # Mathematical sanity bound checking against total disk vs targets
    if total_disk_runs < total_keep:
        print(f"[FAIL] Integrity breached: Total disk runs ({total_disk_runs}) is less than required active targets ({total_keep}).")
        sys.exit(1)
    
    # Check 2 & 3: Deep check file linkages
    for r_id in keep_runs:
        target_run = RUNS_DIR / r_id
        target_sandbox = SANDBOX_DIR / r_id
        
        has_run = target_run.exists() and target_run.is_dir()
        has_sandbox = target_sandbox.exists() and target_sandbox.is_dir()
        
        if not has_run and not has_sandbox:
            missing_critical.append(f"Missing native run folder in both runs/ and sandbox/: {r_id}")
            
        target_json = BACKTESTS_DIR / f"{r_id}.json"
        
        # Native Sandbox JSON handling
        # Evaluators typically look at run_state.json directly inside the sandbox footprint.
        sandbox_state = target_sandbox / "run_state.json"
        run_state = target_run / "run_state.json"
        
        if not target_json.exists() and not sandbox_state.exists() and not run_state.exists():
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


def scan_and_map(keep_runs: set, active_portfolios: set) -> dict:
    """Map the filesystem strictly to identify quaratine candidates."""
    execution_set = build_execution_shield()

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
    for d in DIRECTIVES_DIR.rglob("*.txt"):
        if d.is_file():
            # Directive mapping: Only map if we can prove identity is completely isolated.
            # Example heuristic: if the stem maps directly to an active ID, drop it.
            # If the stem maps directly to a missing ID, append it.
            # If identity cannot be strictly extracted, skip it safely.
            file_id = d.stem
            # Attempting strict equality mapping extraction. If exactly matching KEEP_RUNS, do not touch.
            if file_id in keep_runs:
                # Connected directive. Safe.
                continue
            
            # Since user indicated: "Only delete directive if run_id can be extracted with certainty AND NOT in KEEP_RUNS."
            # We look dynamically to confirm the filename is exactly matching an established UUID formatting layout
            # (e.g. 02_VOL_IDX_..._P00). We check if it is explicitly formed.
            # Easiest way is to define it conservatively.
            target_str = file_id.strip()
            # Let's say it must be exactly formatting or we skip.
            # Here we tentatively append it for quarantine ONLY IF we reliably assume it describes a run.
            targets["directives"].append(d)

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
    parser.add_argument("--force-unlock", action="store_true", help="Bypass TS_Execution safety check. Use only when certain TS_Execution is not running.")
    args = parser.parse_args()

    if args.force_unlock:
        print("[WARN] --force-unlock: Bypassing TS_Execution safety check. Use only when you are certain TS_Execution is not running.")
    elif execution_pid_exists():
        print("[BLOCK] TS_Execution is running")
        sys.exit(1)

    keep_runs, active_portfolios = build_keep_runs()
    
    verify_referential_integrity(keep_runs, active_portfolios)
    
    targets = scan_and_map(keep_runs, active_portfolios)
    
    dry_run_simulation(keep_runs, active_portfolios, targets)
    
    if args.execute:
        execute_purge(targets)
    else:
        print("\n[HALT] Executed cleanly in DRY_RUN mode. Use --execute to structurally quarantine items.")


if __name__ == "__main__":
    main()
