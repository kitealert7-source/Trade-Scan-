"""
cleanup_reconciler.py — SOP_CLEANUP Enforcement (Dry-Run + Execution)

Authority: SOP_CLEANUP (FINAL)
Mode: DRY-RUN (default) / EXECUTE (--execute)
Rewritten to use pandas and Unified Formatter (Zero OpenPyXL Styling / Imports).
"""

import sys
import shutil
import argparse
import subprocess
from pathlib import Path
import pandas as pd

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
RUNS_ROOT = PROJECT_ROOT / "runs"
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
MASTER_SHEET_PATH = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
PORTFOLIO_SHEET_PATH = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"

def load_master_index():
    """
    Read Strategy Master Sheet once.
    Returns:
        rows (list): list of (run_id, strategy_name)
        valid_run_ids (set)
        valid_strategies (set)
    """
    if not MASTER_SHEET_PATH.exists():
        print(f"[ERROR] Master Sheet not found: {MASTER_SHEET_PATH}")
        sys.exit(1)

    try:
        df = pd.read_excel(MASTER_SHEET_PATH)
        # Ensure column names match schema
        # Col A=run_id, B=strategy (we assume by name or position)
        if "run_id" not in df.columns or "strategy" not in df.columns:
            # Try positional fallback if headers are missing/wrong? 
            # SOP says structured. Assume headers exist.
            pass
        
        rows = []
        valid_run_ids = set()
        valid_strategies = set()
        
        for _, row in df.iterrows():
            r_id = str(row.get("run_id", "")).strip()
            s_name = str(row.get("strategy", "")).strip()
            
            if r_id and s_name and r_id != "nan" and s_name != "nan":
                rows.append((r_id, s_name))
                valid_run_ids.add(r_id.casefold())
                valid_strategies.add(s_name.casefold())
                 
        return rows, valid_run_ids, valid_strategies
        
    except Exception as e:
        print(f"[ERROR] Failed to read Master Sheet: {e}")
        sys.exit(1)

def scan_runs(valid_run_ids):
    actions = []
    if not RUNS_ROOT.exists():
        return actions

    for item in RUNS_ROOT.iterdir():
        if item.is_dir():
            run_id = item.name
            if run_id.casefold() not in valid_run_ids:
                actions.append(f"DELETE_RUN_SNAPSHOT runs/{run_id}/")
    return actions

def scan_backtests(valid_strategies):
    actions = []
    if not BACKTESTS_ROOT.exists():
        return actions

    for item in BACKTESTS_ROOT.iterdir():
        name = item.name
        if name == "Strategy_Master_Filter.xlsx": continue
        if name.startswith("batch_summary_") and name.endswith(".csv"): continue
        if name.startswith("."): continue
            
        if item.is_dir():
            if name.casefold() not in valid_strategies:
                actions.append(f"DELETE_BACKTEST_STATE backtests/{name}/")
    return actions
        
def reconcile_orphaned_rows(rows):
    actions_strategies = []
    actions_rows = []
    
    for r_id, s_name in rows:
        run_path = RUNS_ROOT / r_id
        backtest_path = BACKTESTS_ROOT / s_name
        
        exists_run = run_path.exists()
        exists_bt = backtest_path.exists()
        
        if not exists_run or not exists_bt:
            if exists_run:
                actions_strategies.append(f"DELETE_RUN_SNAPSHOT runs/{r_id}/")
            actions_rows.append(f"REMOVE_MASTER_ROW run_id={r_id} strategy={s_name}")
            
    return actions_strategies, actions_rows

def execute_removals(actions_rows):
    """
    Remove rows from Master Sheet using pandas filtering.
    """
    if not actions_rows:
        return
        
    try:
        df = pd.read_excel(MASTER_SHEET_PATH)
        initial_len = len(df)
        
        targets = []
        for action in actions_rows:
            parts = action.split()
            r_id = parts[1].split('=')[1]
            s_name = parts[2].split('=')[1]
            targets.append((r_id, s_name))
            
        # Filter out matching rows
        # Define mask: Keep row if (run_id, strategy) NOT in targets
        mask = []
        for _, row in df.iterrows():
            r = str(row.get("run_id", "")).strip()
            s = str(row.get("strategy", "")).strip()
            mask.append((r, s) not in targets)
            
        df_new = df[mask]
        final_len = len(df_new)
        
        if final_len < initial_len:
            print(f"Removed {initial_len - final_len} rows from Master Sheet.")
            df_new.to_excel(MASTER_SHEET_PATH, index=False)
            
            # Format
            project_root = Path(__file__).parent.parent
            formatter = project_root / "tools" / "format_excel_artifact.py"
            cmd = [sys.executable, str(formatter), "--file", str(MASTER_SHEET_PATH), "--profile", "strategy"]
            subprocess.run(cmd, check=True)
            print("[SUCCESS] Master Sheet updated and formatted.")
        
    except Exception as e:
        print(f"[ERROR] Failed to execute row removals: {e}")

def load_portfolio_index():
    valid_portfolios = set()
    if not PORTFOLIO_SHEET_PATH.exists():
        print(f"[WARN] Portfolio Master Sheet not found at {PORTFOLIO_SHEET_PATH}")
        return valid_portfolios

    try:
        df = pd.read_excel(PORTFOLIO_SHEET_PATH)
        if "portfolio_id" in df.columns:
            for pid in df["portfolio_id"]:
                if pd.notna(pid):
                    valid_portfolios.add(str(pid).strip())
    except Exception as e:
        print(f"[ERROR] Failed to read Portfolio Master Sheet: {e}")
        
    return valid_portfolios

def scan_portfolios(valid_portfolios):
    actions = []
    if not STRATEGIES_ROOT.exists():
        return actions

    for item in STRATEGIES_ROOT.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            if item.name not in valid_portfolios:
                actions.append(f"DELETE_PORTFOLIO_FOLDER strategies/{item.name}/")
    return actions

def reconcile_portfolio_orphans(valid_portfolios):
    actions = []
    for p_id in valid_portfolios:
        p_path = STRATEGIES_ROOT / p_id
        if not p_path.exists():
            actions.append(f"REMOVE_PORTFOLIO_ROW id={p_id}")
    return actions

def execute_portfolio_removals(actions):
    if not actions: return

    try:
        df = pd.read_excel(PORTFOLIO_SHEET_PATH)
        initial_len = len(df)
        
        targets = [a.split('=')[1] for a in actions]
        
        # Filter
        df_new = df[~df["portfolio_id"].astype(str).isin(targets)]
        
        final_len = len(df_new)
        
        if final_len < initial_len:
            print(f"Removed {initial_len - final_len} rows from Portfolio Sheet.")
            df_new.to_excel(PORTFOLIO_SHEET_PATH, index=False)
            
            # Format
            project_root = Path(__file__).parent.parent
            formatter = project_root / "tools" / "format_excel_artifact.py"
            cmd = [sys.executable, str(formatter), "--file", str(PORTFOLIO_SHEET_PATH), "--profile", "portfolio"]
            subprocess.run(cmd, check=True)
            print("[SUCCESS] Portfolio Sheet updated and formatted.")
            
    except Exception as e:
        print(f"[ERROR] Failed to execute portfolio row removals: {e}")

def main():
    parser = argparse.ArgumentParser(description="Cleanup Reconciler (Clean Engine)")
    parser.add_argument("--execute", action="store_true", help="Execute planned deletions")
    args = parser.parse_args()

    rows, valid_run_ids, valid_strategies = load_master_index()
    strategy_to_run_id = {s: r for r, s in rows}
    
    all_strategies = []
    all_backtests = []
    all_rows = []
    
    zombie_runs = scan_runs(valid_run_ids)
    zombie_bt = scan_backtests(valid_strategies)
    all_strategies.extend(zombie_runs)
    all_backtests.extend(zombie_bt)
    
    leftover_runs, orphan_rows = reconcile_orphaned_rows(rows)
    all_strategies.extend(leftover_runs)
    all_rows.extend(orphan_rows)
    
    failed_run_ids = set()
    
    # Process Actions
    for action in sorted(list(set(all_strategies))):
        print(action)
        if args.execute:
            parts = action.split()
            path_str = parts[1]
            try:
                r_id = path_str.split('/')[1]
                target_path = PROJECT_ROOT / path_str
                if target_path.exists():
                    shutil.rmtree(target_path)
            except Exception as e:
                print(f"[ERROR] Failed to delete {path_str}: {e}")
                failed_run_ids.add(r_id)

    for action in sorted(list(set(all_backtests))):
        print(action)
        if args.execute:
            parts = action.split()
            path_str = parts[1]
            try:
                s_name = path_str.split('/')[1]
                target_path = PROJECT_ROOT / path_str
                if target_path.exists():
                    shutil.rmtree(target_path)
            except Exception as e:
                print(f"[ERROR] Failed to delete {path_str}: {e}")
                if s_name in strategy_to_run_id:
                    failed_run_ids.add(strategy_to_run_id[s_name])

    valid_row_actions = []
    for action in all_rows:
        parts = action.split()
        r_id = parts[1].split('=')[1]
        if r_id in failed_run_ids:
            print(f"[SKIP] Keeping row for failed cleanup: {r_id}")
            continue
        print(action)
        valid_row_actions.append(action)
        
    if args.execute and valid_row_actions:
        execute_removals(valid_row_actions)

    print("\n--- PORTFOLIO LAYER (ADVISORY ONLY) ---")
    valid_portfolios = load_portfolio_index()
    zombie_portfolios = scan_portfolios(valid_portfolios)
    orphan_portfolios = reconcile_portfolio_orphans(valid_portfolios)

    if not zombie_portfolios and not orphan_portfolios:
        print("[PASS] Portfolio Layer is clean.")
    else:
        for action in zombie_portfolios:
            print(f"[ADVISORY] ZOMBIE PORTFOLIO: {action}")
        for action in orphan_portfolios:
            print(f"[ADVISORY] ORPHAN ROW: {action}")

if __name__ == "__main__":
    main()
