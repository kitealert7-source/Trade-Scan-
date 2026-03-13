"""
cleanup_reconciler.py -- New Extremely Safe Cleanup Sweep (Registry-Governed)

Authority: JSON Run Registry & explicit portfolio dependencies.
Excel parsing has been completely abandoned for safety.
"""

import sys
import shutil
import argparse
import time
from pathlib import Path
import json

# Project Paths
PROJECT_ROOT = Path(__file__).parent.parent
RUNS_ROOT = PROJECT_ROOT / "runs"
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
CANDIDATES_ROOT = PROJECT_ROOT / "candidates"  # Phase 2 implementation target

sys.path.insert(0, str(PROJECT_ROOT))
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
    
    # 2. Identify deletable runs based STRICTLY on the plan logic:
    # IF tier == "sandbox" AND status == "complete" AND run_id not referenced
    for run_id, record in reg_data.items():
        if record.get("tier") == "sandbox" and record.get("status") == "complete":
            if run_id not in active_portfolios:
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
        rel_view = Path(ui_view).relative_to(PROJECT_ROOT)
        print(f"  - DELETE {rel_view}/ (Disposable UI View)")

    def is_path_safe(p: Path) -> bool:
        """Strict physical guardrail for filesystem deletions."""
        p_abs = p.resolve()
        root_abs = PROJECT_ROOT.resolve()
        
        # 1. Must be under PROJECT_ROOT
        if root_abs not in p_abs.parents:
            return False
        
        # 2. Must NOT be a system-critical folder
        forbidden = ["strategies", "candidates", "registry", "tools", "data_access"]
        for part in p_abs.parts:
            if part.lower() in forbidden:
                return False
        
        # 3. Must be inside an allowed cleanup scope
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
                print(f"  [DELETED] {ui_path.relative_to(PROJECT_ROOT)}/")
                
        # Persist cleaned registry
        from tools.system_registry import _save_registry_atomic
        _save_registry_atomic(reg_data)
        print("[SUCCESS] Cleanup and Registry Purge Complete.")
    else:
        print("\n[INFO] Dry-run complete. Use --execute to apply.")

if __name__ == "__main__":
    main()
