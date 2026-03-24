import pandas as pd
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import MASTER_FILTER_PATH, POOL_DIR, RUNS_DIR, CANDIDATE_FILTER_PATH
from tools.system_registry import _load_registry, _save_registry_atomic

MASTER_SHEET = MASTER_FILTER_PATH

def filter_strategies():
    if not os.path.exists(MASTER_SHEET):
        print(f"ABORT: Error: {MASTER_SHEET} not found.")
        sys.exit(1)

    try:
        df = pd.read_excel(MASTER_SHEET)
    except Exception as e:
        print(f"ABORT: Error reading {MASTER_SHEET}: {e}")
        sys.exit(1)

    # Required metrics for promotion
    required_cols = [
        'profit_factor', 
        'return_dd_ratio', 
        'expectancy', 
        'total_trades', 
        'sharpe_ratio', 
        'max_dd_pct',
        'run_id',
        'strategy'
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        print(f"ABORT: Missing required columns in master sheet: {missing_cols}")
        print("Ensure Stage-3 compilation includes max_dd_pct.")
        sys.exit(1)

    nan_mask = df[required_cols].isna().any(axis=1)
    if nan_mask.any():
        affected_runs = df.loc[nan_mask, 'run_id'].tolist()
        print(f"ABORT: NaN detected in required metrics for run_ids: {affected_runs}")
        sys.exit(1)

    total_eval_runs = len(df)
    
    # Relaxed Criteria (User Proposed)
    # Note: Max DD is typically negative in internal sheets (e.g. -0.15 for 15% DD)
    # The user threshold "Max DD <= 80%" means the number should be >= -80.0 (or >= -0.80)
    mask = (
        (df['total_trades'] >= 40) &
        (df['profit_factor'] >= 1.05) &
        (df['return_dd_ratio'] >= 0.6) &
        (df['expectancy'] >= 0.0) &
        (df['sharpe_ratio'] >= 0.3) &
        (df['max_dd_pct'] >= -80.0) 
    )

    passed_df = df[mask].copy()
    
    # --- CANDIDATE LEDGER GENERATION ---
    # Append+dedup semantics: previously passing strategies are never evicted,
    # even if they are temporarily absent from the Master Filter (e.g., during
    # re-run cleanup cycles where old rows are removed before re-running).
    if not passed_df.empty:
        try:
            # Step 1: Archive existing candidates file before any mutation.
            if CANDIDATE_FILTER_PATH.exists():
                archive_dir = CANDIDATE_FILTER_PATH.parent / "archive"
                archive_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                shutil.copy2(
                    CANDIDATE_FILTER_PATH,
                    archive_dir / f"Filtered_Strategies_Passed_{ts}.xlsx",
                )
                print(f"[CANDIDATES] Archived previous candidates to {archive_dir.name}/Filtered_Strategies_Passed_{ts}.xlsx")

            # Step 2: Read-modify-write with dedup on run_id (mirrors stage3_compiler pattern).
            if CANDIDATE_FILTER_PATH.exists():
                try:
                    df_existing = pd.read_excel(CANDIDATE_FILTER_PATH)
                    existing_run_ids = (
                        set(df_existing["run_id"].astype(str).tolist())
                        if "run_id" in df_existing.columns
                        else set()
                    )
                    df_new_rows = passed_df[~passed_df["run_id"].astype(str).isin(existing_run_ids)]
                    df_merged = pd.concat([df_existing, df_new_rows], ignore_index=True)
                    print(f"[CANDIDATES] Merged: {len(existing_run_ids)} existing + {len(df_new_rows)} new = {len(df_merged)} total")
                except Exception as read_err:
                    print(f"[WARN] Could not read existing candidates file ({read_err}) — writing fresh.")
                    df_merged = passed_df
            else:
                df_merged = passed_df

            df_merged.to_excel(CANDIDATE_FILTER_PATH, index=False)
            print(f"[SUCCESS] Candidate ledger written: {CANDIDATE_FILTER_PATH}")

            # Step 3: Format the merged ledger.
            import subprocess
            formatter_path = PROJECT_ROOT / "tools" / "format_excel_artifact.py"
            try:
                subprocess.run(
                    [sys.executable, str(formatter_path), "--file", str(CANDIDATE_FILTER_PATH), "--profile", "strategy"],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"[WARN] Failed to format candidate ledger: {e.stderr.decode()}")

        except Exception as e:
            print(f"[ERROR] Failed to generate candidate ledger: {e}")
    # -----------------------------------

    if passed_df.empty:
        print("Total evaluated:", total_eval_runs)
        print("Passed this run: 0")
        return

    # 1. Load Registry
    reg = _load_registry()
    promoted_count = 0
    migration_count = 0

    # 2. Process Passing Strategies
    for _, row in passed_df.iterrows():
        run_id = str(row['run_id'])
        strat_name = str(row['strategy'])
        
        if run_id not in reg:
            continue
            
        current_tier = reg[run_id].get("tier", "sandbox")
        if current_tier == "candidate":
            continue
            
        # 1. Update Registry Tier (Authoritative)
        reg[run_id]["tier"] = "sandbox"
        _save_registry_atomic(reg) # Persist immediately
        promoted_count += 1
        
        # 2. Physical Migration
        src_path = RUNS_DIR / run_id
        dest_path = POOL_DIR / run_id

        if src_path.exists() and not dest_path.exists():
            try:
                POOL_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_path), str(dest_path))
                migration_count += 1
                print(f"[MIGRATED] {run_id} -> sandbox/")
            except Exception as e:
                print(f"[ERROR] Physical migration failed for {run_id}: {e}")
                # Note: We do NOT revert the tier. The registry is authoritative.
                # Reconcile or a future run will fix the physical location.

    # Final Output Summary
    print("Total evaluated:", total_eval_runs)
    print("Passed criteria:", len(passed_df))
    print("Newly promoted to candidate:", promoted_count)
    print("Physically migrated:", migration_count)

if __name__ == "__main__":
    filter_strategies()
