import sys
import shutil
import argparse
import time
import json
from datetime import datetime, timezone
from pathlib import Path

# Project Paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import RUNS_DIR, BACKTESTS_DIR, STRATEGIES_DIR, SELECTED_DIR

RUNS_ROOT = RUNS_DIR
BACKTESTS_ROOT = BACKTESTS_DIR
STRATEGIES_ROOT = STRATEGIES_DIR
CANDIDATES_ROOT = SELECTED_DIR

from tools.system_registry import _load_registry, get_active_portfolio_runs, reconcile_registry

def get_run_ui_folder(run_id: str) -> Path:
    """Read run_metadata.json to find the corresponding UI view in backtests/"""
    meta_path = RUNS_ROOT / run_id / "data" / "run_metadata.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            strat = data.get("strategy_name")
            if strat:
                return BACKTESTS_ROOT / strat
        except Exception:
            pass
    return None

def main():
    parser = argparse.ArgumentParser(description="Extremely Safe Cleanup Sweep")
    parser.add_argument("--execute", action="store_true", help="Execute planned deletions")
    args = parser.parse_args()

    print("--- STARTING REGISTRY-GOVERNED CLEANUP ---")
    
    # 1. Startup Reconciliation (Always enforce state alignment before cleanup)
    reconcile_registry()
    
    reg_data = _load_registry()
    active_portfolios = get_active_portfolio_runs()
    
    runs_to_delete = []
    ui_views_to_delete = []

    # Load BURN_IN protected run_ids from candidate ledger.
    # Any strategy with candidate_status == "BURN_IN" is exempt from cleanup.
    _burn_in_run_ids: set[str] = set()
    try:
        _candidate_path = CANDIDATES_ROOT / "Filtered_Strategies_Passed.xlsx"
        if _candidate_path.exists():
            import pandas as _pd
            _cdf = _pd.read_excel(_candidate_path, usecols=["run_id", "candidate_status"])
            _burn_in_run_ids = set(
                _cdf.loc[_cdf["candidate_status"].astype(str).str.strip() == "BURN_IN", "run_id"]
                .astype(str).tolist()
            )
            if _burn_in_run_ids:
                print(f"[GUARD] {len(_burn_in_run_ids)} BURN_IN run(s) protected from cleanup")
    except Exception as _e:
        print(f"[WARN] Could not load BURN_IN guard from candidate ledger: {_e}")

    # 2. Identify deletable runs based STRICTLY on the plan logic:
    # IF tier == "sandbox" AND status in {complete, aborted, failed} AND run_id not referenced
    # AND run_id is not BURN_IN protected
    # ABORTED/failed runs are eligible but must be >1 hour old (forensic cool-down).
    # This prevents deleting runs the watchdog just marked or that need investigation.
    _deletable_statuses = {"complete", "aborted", "failed"}
    _cooldown_statuses = {"aborted", "failed"}  # require age check
    _COOLDOWN_SECONDS = 3600  # 1 hour
    _now_ts = datetime.now(timezone.utc).timestamp()

    for run_id, record in reg_data.items():
        status = record.get("status", "")
        if record.get("tier") == "sandbox" and status in _deletable_statuses:
            if run_id not in active_portfolios:
                if run_id in _burn_in_run_ids:
                    print(f"  [PROTECTED] {run_id} — BURN_IN status, skipping")
                    continue
                # Cool-down guard for aborted/failed: check run_state.json timestamp
                if status in _cooldown_statuses:
                    state_file = RUNS_ROOT / run_id / "run_state.json"
                    if state_file.exists():
                        try:
                            sd = json.loads(state_file.read_text(encoding="utf-8"))
                            last_ts = sd.get("last_transition", "")
                            if last_ts:
                                run_age = _now_ts - datetime.fromisoformat(
                                    last_ts.replace("Z", "+00:00")
                                ).timestamp()
                                if run_age < _COOLDOWN_SECONDS:
                                    print(f"  [COOLDOWN] {run_id} — {status} {run_age:.0f}s ago, skipping (min {_COOLDOWN_SECONDS}s)")
                                    continue
                        except Exception:
                            pass  # Can't parse timestamp — allow deletion
                runs_to_delete.append(run_id)
                ui_folder = get_run_ui_folder(run_id)
                if ui_folder and ui_folder.exists() and str(ui_folder) not in ui_views_to_delete:
                    ui_views_to_delete.append(str(ui_folder))
                    
    # 3. Execution
    if not runs_to_delete:
        print("[PASS] No sandbox runs eligible for deletion.")
        sys.exit(0)
        
    print(f"[PLAN] {len(runs_to_delete)} atomic runs flagged for deletion.")
    for r_id in runs_to_delete:
        print(f"  - DELETE runs/{r_id}/")
        
    for ui_view in ui_views_to_delete:
        try:
            rel_view = Path(ui_view).relative_to(PROJECT_ROOT)
        except ValueError:
            rel_view = ui_view
        print(f"  - DELETE {rel_view}/ (Disposable UI View)")

    def is_path_safe(p: Path) -> bool:
        """Strict physical guardrail for filesystem deletions."""
        p_abs = p.resolve()

        # 1. Must NOT be a system-critical folder
        forbidden = ["strategies", "candidates", "registry", "tools", "data_access", "waiting"]
        for part in p_abs.parts:
            if part.lower() in forbidden:
                return False

        # 2. Must be inside an allowed cleanup scope (RUNS_ROOT or BACKTESTS_ROOT)
        allowed_scopes = [RUNS_ROOT.resolve(), BACKTESTS_ROOT.resolve()]
        in_scope = any(scope in p_abs.parents for scope in allowed_scopes)

        return in_scope

    if args.execute:
        print("\n[EXECUTE] Removing files...")
        
        for r_id in runs_to_delete:
            r_path = RUNS_ROOT / r_id
            
            if not is_path_safe(r_path):
                print(f"  [ABORT] Boundary violation detected for {r_path}")
                raise RuntimeError(f"CRITICAL BOUNDARY VIOLATION: {r_path}")
                
            if r_path.exists():
                shutil.rmtree(r_path)
                print(f"  [DELETED] runs/{r_id}/")
                
            # Pop from registry to keep it clean
            reg_data.pop(r_id, None)
            
        for ui_view in ui_views_to_delete:
            ui_path = Path(ui_view)
            
            if not is_path_safe(ui_path):
                print(f"  [SKIP] Boundary violation for disposable view: {ui_path}")
                continue

            if ui_path.exists():
                shutil.rmtree(ui_path)
                try:
                    disp = ui_path.relative_to(PROJECT_ROOT)
                except ValueError:
                    disp = ui_path
                print(f"  [DELETED] {disp}/")
                
        # Persist cleaned registry
        from tools.system_registry import _save_registry_atomic
        _save_registry_atomic(reg_data)
        print("[SUCCESS] Cleanup and Registry Purge Complete.")
    else:
        print("\n[INFO] Dry-run complete. Use --execute to apply.")

if __name__ == "__main__":
    main()
