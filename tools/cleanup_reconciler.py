"""
cleanup_reconciler.py — SOP_CLEANUP Enforcement (Dry-Run + Execution)

Authority: SOP_CLEANUP (FINAL)
Mode: DRY-RUN (default) / EXECUTE (--execute)
Rewritten to use pandas and Unified Formatter (Zero OpenPyXL Styling / Imports).
"""

import sys
import os
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
RUNS_ROOT = PROJECT_ROOT / "runs"
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
MASTER_SHEET_PATH = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
PORTFOLIO_SHEET_PATH = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"
REPORTS_ROOT = PROJECT_ROOT / "reports_summary"
OUTPUTS_REPORTS_ROOT = PROJECT_ROOT / "outputs" / "reports"
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"
TMP_ROOT = PROJECT_ROOT / "tmp"

# Configurable thresholds
TMP_MAX_AGE_HOURS = 24
BAK_MAX_AGE_DAYS = 7

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
        
        rows = []
        valid_run_ids = set()
        valid_strategies = set()
        valid_base_strategies = set()
        
        for _, row in df.iterrows():
            r_id = str(row.get("run_id", "")).strip()
            s_name = str(row.get("strategy", "")).strip()
            
            if r_id and s_name and r_id != "nan" and s_name != "nan":
                rows.append((r_id, s_name))
                valid_run_ids.add(r_id.casefold())
                valid_strategies.add(s_name.casefold())
                # Also derive base strategy name by stripping the trailing _SYMBOL suffix
                # e.g. AK32_FX_PORTABILITY_4H_AUDJPY -> AK32_FX_PORTABILITY_4H
                parts = s_name.rsplit('_', 1)
                if len(parts) == 2 and len(parts[1]) <= 7:  # symbol suffix is short (AUDJPY, USDJPY etc.)
                    valid_base_strategies.add(parts[0].casefold())
                else:
                    valid_base_strategies.add(s_name.casefold())
                 
        return rows, valid_run_ids, valid_strategies, valid_base_strategies
        
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

def scan_backtests(valid_strategies, valid_base_strategies):
    actions = []
    if not BACKTESTS_ROOT.exists():
        return actions

    for item in BACKTESTS_ROOT.iterdir():
        name = item.name
        if name == "Strategy_Master_Filter.xlsx": continue
        if name.startswith("."): continue

        # Orphaned batch_summary_<base_strategy>.csv check
        # batch_summary files use base strategy names (without symbol suffix)
        if name.startswith("batch_summary_") and name.endswith(".csv"):
            base_name = name[len("batch_summary_"):-len(".csv")]
            if base_name.casefold() not in valid_base_strategies:
                actions.append(f"DELETE_BATCH_SUMMARY backtests/{name}")
            continue

        if item.is_dir():
            if name.casefold() not in valid_strategies:
                actions.append(f"DELETE_BACKTEST_STATE backtests/{name}/")
    return actions

def scan_reports(valid_base_strategies):
    actions = []
    if not REPORTS_ROOT.exists():
        return actions

    valid_strats_set = set()
    valid_bts_set = set()
    
    if STRATEGIES_ROOT.exists():
        for d in STRATEGIES_ROOT.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                valid_strats_set.add(d.name)
    if BACKTESTS_ROOT.exists():
         for d in BACKTESTS_ROOT.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                valid_bts_set.add(d.name)

    for item in REPORTS_ROOT.iterdir():
        if not item.is_file(): continue
        name = item.name
        base_name = None
        if name.startswith("REPORT_") and name.endswith(".md"):
            base_name = name[len("REPORT_"):-len(".md")]
        elif name.startswith("PORTFOLIO_") and name.endswith(".md"):
            base_name = name[len("PORTFOLIO_"):-len(".md")]
            
        if not base_name:
            continue
            
        if base_name.casefold() not in valid_base_strategies:
            actions.append(f"DELETE_REPORT reports_summary/{name}")
        else:
            matched_folder = None
            for folder in list(valid_strats_set) + list(valid_bts_set):
                if folder.casefold() == base_name.casefold():
                    matched_folder = folder
                    break
                    
            if matched_folder:
                if matched_folder in valid_strats_set:
                    dest = f"strategies/{matched_folder}/{name}"
                else:
                    dest = f"backtests/{matched_folder}/{name}"
                actions.append(f"MOVE_REPORT reports_summary/{name} -> {dest}")
                
    return actions

def scan_outputs_reports(valid_strategies, valid_portfolios):
    actions = []
    if not OUTPUTS_REPORTS_ROOT.exists():
        return actions

    import re
    # Determine what folders strictly exist right now
    valid_strats_set = set()
    valid_bts_set = set()
    
    if STRATEGIES_ROOT.exists():
        for d in STRATEGIES_ROOT.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                valid_strats_set.add(d.name)
    if BACKTESTS_ROOT.exists():
         for d in BACKTESTS_ROOT.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                valid_bts_set.add(d.name)
                
    all_valid_folders = sorted(list(valid_strats_set) + list(valid_bts_set), key=len, reverse=True)

    for item in OUTPUTS_REPORTS_ROOT.iterdir():
        if not item.is_file() or not item.name.endswith('.md'):
            continue
            
        name = item.name
        search_name = name
        if search_name.startswith('ROBUSTNESS_'): search_name = search_name.replace('ROBUSTNESS_', '')
        if search_name.startswith('USDCHF_ISOLATION_'): search_name = search_name.replace('USDCHF_ISOLATION_', '')
        if search_name.startswith('Risk_Comparison_'): search_name = search_name.replace('Risk_Comparison_', '')
        if search_name.startswith('PORTFOLIO_'): search_name = search_name.replace('PORTFOLIO_', '')
        if search_name.startswith('REPORT_'): search_name = search_name.replace('REPORT_', '')
        
        matched_folder = None
        for f in all_valid_folders:
            if f in search_name:
                matched_folder = f
                break
                
        if matched_folder:
            if matched_folder in valid_strats_set:
                dest = f"strategies/{matched_folder}/{name}"
            else:
                dest = f"backtests/{matched_folder}/{name}"
            actions.append(f"MOVE_REPORT outputs/reports/{name} -> {dest}")
        else:
            actions.append(f"DELETE_ORPHANED_REPORT outputs/reports/{name}")
            
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

# --- WORKSPACE HYGIENE SCANS ---

def scan_temp_scripts():
    """Scan tmp/ folder and project root for tmp_*.py files older than TMP_MAX_AGE_HOURS."""
    actions = []
    cutoff = time.time() - (TMP_MAX_AGE_HOURS * 3600)

    # Primary: scan tmp/ folder
    if TMP_ROOT.exists():
        for item in TMP_ROOT.iterdir():
            if item.is_file() and item.name.endswith(".py"):
                mtime = item.stat().st_mtime
                age_hours = (time.time() - mtime) / 3600
                if mtime < cutoff:
                    actions.append((f"DELETE_TEMP_SCRIPT tmp/{item.name}", item, True))
                else:
                    actions.append((f"TEMP_SCRIPT_RECENT tmp/{item.name} (age={age_hours:.1f}h)", item, False))

    # Fallback: detect stray tmp_*.py at project root (misplaced)
    for item in PROJECT_ROOT.iterdir():
        if item.is_file() and item.name.startswith("tmp_") and item.name.endswith(".py"):
            actions.append((f"STRAY_TEMP_SCRIPT {item.name} (should be in tmp/)", item, False))
    return actions


def scan_orphan_strategy_folders(valid_portfolios, valid_base_strategies):
    """Scan strategies/ for folders not in Master Portfolio Sheet or Master Filter."""
    actions = []
    if not STRATEGIES_ROOT.exists():
        return actions

    for item in STRATEGIES_ROOT.iterdir():
        if not item.is_dir() or item.name.startswith("."):
            continue
        name = item.name
        if name in valid_portfolios:
            continue
        if name.casefold() in valid_base_strategies:
            continue
        actions.append(f"ORPHAN_STRATEGY_FOLDER strategies/{name}/")
    return actions


def scan_bak_archives():
    """Scan runs/ for .bak* files older than BAK_MAX_AGE_DAYS."""
    actions = []
    if not RUNS_ROOT.exists():
        return actions

    cutoff = time.time() - (BAK_MAX_AGE_DAYS * 86400)
    for bak_file in RUNS_ROOT.rglob("*.bak*"):
        if bak_file.is_file() and bak_file.stat().st_mtime < cutoff:
            rel = bak_file.relative_to(PROJECT_ROOT)
            actions.append((f"DELETE_BAK_ARCHIVE {rel}", bak_file))
    return actions


def scan_shelved_directives():
    """Scan backtest_directives/ for .shelved files."""
    actions = []
    if not DIRECTIVES_ROOT.exists():
        return actions

    for item in DIRECTIVES_ROOT.rglob("*.shelved"):
        rel = item.relative_to(PROJECT_ROOT)
        actions.append(f"SHELVED_DIRECTIVE_DETECTED {rel}")
    return actions


def scan_failed_states():
    """Scan runs/ for FAILED run_state.json and directive_state.json files."""
    actions = []
    if not RUNS_ROOT.exists():
        return actions

    for run_dir in RUNS_ROOT.iterdir():
        if not run_dir.is_dir():
            continue
        # Check run_state.json
        rs = run_dir / "run_state.json"
        if rs.exists():
            try:
                data = json.loads(rs.read_text(encoding="utf-8"))
                if data.get("current_state") == "FAILED":
                    actions.append(f"FAILED_RUN_STATE runs/{run_dir.name}/")
            except Exception:
                pass
        # Check directive_state.json
        ds = run_dir / "directive_state.json"
        if ds.exists():
            try:
                data = json.loads(ds.read_text(encoding="utf-8"))
                if data.get("current_state") == "FAILED":
                    actions.append(f"FAILED_DIRECTIVE_STATE runs/{run_dir.name}/")
            except Exception:
                pass
    return actions


def main():
    parser = argparse.ArgumentParser(description="Cleanup Reconciler (Clean Engine)")
    parser.add_argument("--execute", action="store_true", help="Execute planned deletions")
    args = parser.parse_args()

    rows, valid_run_ids, valid_strategies, valid_base_strategies = load_master_index()
    strategy_to_run_id = {s: r for r, s in rows}
    
    all_strategies = []
    all_backtests = []
    all_rows = []
    
    zombie_runs = scan_runs(valid_run_ids)
    zombie_bt = scan_backtests(valid_strategies, valid_base_strategies)
    zombie_reports = scan_reports(valid_base_strategies)
    
    valid_portfolios = load_portfolio_index()
    outputs_reports_actions = scan_outputs_reports(valid_strategies, valid_portfolios)
    
    all_strategies.extend(zombie_runs)
    all_backtests.extend(zombie_bt)
    all_backtests.extend(zombie_reports)
    all_backtests.extend(outputs_reports_actions)
    
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
            action_type = parts[0]
            path_str = parts[1]
            try:
                target_path = PROJECT_ROOT / path_str
                if action_type in ["DELETE_BATCH_SUMMARY", "DELETE_REPORT", "DELETE_ORPHANED_REPORT"]:
                    # File deletion
                    if target_path.exists():
                        target_path.unlink()
                elif action_type == "MOVE_REPORT":
                    # parts: MOVE_REPORT src_path -> dest_path
                    src_path = PROJECT_ROOT / parts[1]
                    dest_path = PROJECT_ROOT / parts[3]
                    if src_path.exists():
                        shutil.move(src_path, dest_path)
                else:
                    # Directory deletion
                    s_name = path_str.split('/')[1]
                    if target_path.exists():
                        shutil.rmtree(target_path)
            except Exception as e:
                print(f"[ERROR] Failed to delete {path_str}: {e}")
                if action_type not in ["DELETE_BATCH_SUMMARY", "DELETE_REPORT"]:
                    s_name = path_str.split('/')[1]
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
    zombie_portfolios = scan_portfolios(valid_portfolios)
    orphan_portfolios = reconcile_portfolio_orphans(valid_portfolios)

    if not zombie_portfolios and not orphan_portfolios:
        print("[PASS] Portfolio Layer is clean.")
    else:
        for action in zombie_portfolios:
            print(f"[ADVISORY] ZOMBIE PORTFOLIO: {action}")
        for action in orphan_portfolios:
            print(f"[ADVISORY] ORPHAN ROW: {action}")

    # --- WORKSPACE HYGIENE ---
    print("\n--- WORKSPACE HYGIENE ---")
    hygiene_count = 0

    # 1. Temporary scripts
    temp_actions = scan_temp_scripts()
    for label, filepath, is_old in temp_actions:
        print(f"[HYGIENE] {label}")
        hygiene_count += 1
        if args.execute and is_old:
            try:
                filepath.unlink()
                print(f"  [DELETED] {filepath.name}")
            except Exception as e:
                print(f"  [ERROR] {e}")

    # 2. Orphan strategy folders
    orphan_strats = scan_orphan_strategy_folders(valid_portfolios, valid_base_strategies)
    for action in orphan_strats:
        print(f"[HYGIENE] {action}")
        hygiene_count += 1

    # 3. Archive file accumulation
    bak_actions = scan_bak_archives()
    for label, filepath in bak_actions:
        print(f"[HYGIENE] {label}")
        hygiene_count += 1
        if args.execute:
            try:
                filepath.unlink()
                print(f"  [DELETED] {filepath.name}")
            except Exception as e:
                print(f"  [ERROR] {e}")

    # 4. Shelved directives
    shelved = scan_shelved_directives()
    for action in shelved:
        print(f"[HYGIENE] {action}")
        hygiene_count += 1

    # 5. Failed states
    failed = scan_failed_states()
    for action in failed:
        print(f"[HYGIENE] {action}")
        hygiene_count += 1

    if hygiene_count == 0:
        print("[PASS] Workspace is clean.")
    else:
        print(f"\n[HYGIENE SUMMARY] {hygiene_count} issue(s) detected.")

if __name__ == "__main__":
    main()
