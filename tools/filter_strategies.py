"""
Strict Strategy Filter Script — Append-Only Passed Ledger With Portfolio Flag Authority

Filtered_Strategies_Passed.xlsx is an append-only ledger of passed strategies.
Column IN_PORTFOLIO (Column AB) is a manual promotion flag used by the portfolio module.
Agent must NEVER modify existing IN_PORTFOLIO values.
"""

import pandas as pd
import os
import sys
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl import load_workbook
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import MASTER_FILTER_PATH, CANDIDATE_FILTER_PATH

MASTER_SHEET = MASTER_FILTER_PATH
PASSED_SHEET = CANDIDATE_FILTER_PATH

def apply_data_validation(file_path):
    """
    Applies an Excel DataValidation dropdown (TRUE/FALSE) to the IN_PORTFOLIO column.
    Removes existing validations targeting this column to prevent duplication,
    and extends validation seamlessly to the maximum Excel row (1048576).
    """
    try:
        wb = load_workbook(file_path)
        ws = wb.active
        
        # Find the IN_PORTFOLIO column letter
        col_letter = None
        for cell in ws[1]:
            if cell.value == "IN_PORTFOLIO":
                col_letter = cell.column_letter
                break
                
        if not col_letter:
            wb.close()
            return

        # 2️⃣ Prevent Validation Duplication
        # Remove any existing DataValidation rules targeting the IN_PORTFOLIO column.
        clean_validations = []
        for dv in ws.data_validations.dataValidation:
            keep_this_dv = True
            sqref_str = str(dv.sqref)
            # If the column letter appears in the reference string, we drop this rule
            # to cleanly replace it. (e.g. 'AB2:AB10000', 'AB')
            if col_letter in sqref_str:
                keep_this_dv = False
            
            if keep_this_dv:
                clean_validations.append(dv)

        # Clear existing and reassign
        ws.data_validations.dataValidation = []
        for clean_dv in clean_validations:
            ws.add_data_validation(clean_dv)
            
        # Create new validation rule
        dv = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=True)
        # dv.error = 'Your entry is not in the list (TRUE, FALSE)'
        # dv.errorTitle = 'Invalid Entry'
        # dv.prompt = 'Please select from the list'
        # dv.promptTitle = 'Select Portfolio Status'
        
        # 1️⃣ Expand Data Validation Range to max
        dv.add(f'{col_letter}2:{col_letter}1048576')
        ws.add_data_validation(dv)
        
        wb.save(file_path)
    except Exception as e:
        print(f"ABORT: Failed to apply data validation: {e}")
        sys.exit(1)

def filter_strategies():
    if not os.path.exists(MASTER_SHEET):
        print(f"ABORT: Error: {MASTER_SHEET} not found.")
        sys.exit(1)

    try:
        df = pd.read_excel(MASTER_SHEET)
    except Exception as e:
        print(f"ABORT: Error reading {MASTER_SHEET}: {e}")
        sys.exit(1)

    required_cols = [
        'profit_factor', 
        'return_dd_ratio', 
        'expectancy', 
        'total_trades', 
        'sharpe_ratio', 
        'run_id'
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        print(f"ABORT: Missing required columns in master sheet: {missing_cols}")
        sys.exit(1)

    nan_mask = df[required_cols].isna().any(axis=1)
    if nan_mask.any():
        affected_runs = df.loc[nan_mask, 'run_id'].tolist()
        print(f"ABORT: NaN detected in required metrics for run_ids: {affected_runs}")
        sys.exit(1)

    total_eval_runs = len(df)
    
    mask = (
        (df['profit_factor'] >= 1.3) &
        (df['return_dd_ratio'] >= 1.8) &
        (df['expectancy'] >= 2.5) &
        (df['total_trades'] >= 80) &
        (df['sharpe_ratio'] >= 1.2)
    )

    passed_df = df[mask].copy()
    master_cols = list(df.columns)
    
    if "IN_PORTFOLIO" not in master_cols:
        master_cols.append("IN_PORTFOLIO")
    
    for col in master_cols:
         if col not in passed_df.columns:
             passed_df[col] = pd.NA

    passed_df["IN_PORTFOLIO"] = False
    passed_df = passed_df[master_cols] 

    temp_passed = str(PASSED_SHEET).replace(".xlsx", "_TEMP.xlsx")
    newly_appended = 0
    total_rows_in_ledger = 0

    if os.path.exists(PASSED_SHEET):
        try:
            existing_df = pd.read_excel(PASSED_SHEET)
            
            # 3️⃣ Enforce Column Integrity
            if "IN_PORTFOLIO" not in existing_df.columns:
                print(f"ABORT: IN_PORTFOLIO column missing from existing ledger: {PASSED_SHEET}")
                sys.exit(1)

            total_rows_in_ledger = len(existing_df)
            
            existing_run_ids = set(existing_df['run_id'].dropna().astype(str).tolist())
            passed_df['run_id_str'] = passed_df['run_id'].astype(str)
            
            new_runs_df = passed_df[~passed_df['run_id_str'].isin(existing_run_ids)].copy()
            new_runs_df.drop(columns=['run_id_str'], inplace=True)
            
            newly_appended = len(new_runs_df)
            
            if newly_appended > 0:
                for col in existing_df.columns:
                    if col not in new_runs_df.columns:
                        new_runs_df[col] = pd.NA
                
                new_runs_df = new_runs_df[existing_df.columns]
                
                final_df = pd.concat([existing_df, new_runs_df], ignore_index=True)
                total_rows_in_ledger = len(final_df)
                
                final_df.to_excel(temp_passed, index=False, engine='openpyxl')
                
                try:
                    formatter_path = os.path.join(os.path.dirname(__file__), "format_excel_artifact.py")
                    cmd = [sys.executable, formatter_path, "--file", temp_passed, "--profile", "strategy"]
                    import subprocess
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
                except Exception:
                    pass
                
                apply_data_validation(temp_passed)
                
                try:
                    os.replace(temp_passed, PASSED_SHEET)
                except Exception as e:
                    print(f"ABORT: Replace failed {e}")
                    if os.path.exists(temp_passed): os.remove(temp_passed)
                    sys.exit(1)
            else:
                 pass

        except Exception as e:
            if str(e).startswith("ABORT"): 
                print(e)
            else:
                print(f"ABORT: Error processing existing passed sheet {PASSED_SHEET}: {e}")
            sys.exit(1)
            
    else:
        newly_appended = len(passed_df)
        total_rows_in_ledger = newly_appended
        
        try:
            passed_df.to_excel(temp_passed, index=False, engine='openpyxl')
            
            try:
                formatter_path = os.path.join(os.path.dirname(__file__), "format_excel_artifact.py")
                cmd = [sys.executable, formatter_path, "--file", temp_passed, "--profile", "strategy"]
                import subprocess
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            except Exception:
                pass
            
            apply_data_validation(temp_passed)
                
            os.replace(temp_passed, PASSED_SHEET)
        except Exception as e:
            if str(e).startswith("ABORT"): 
                print(e)
            else:
                print(f"ABORT: Error writing to {PASSED_SHEET}: {e}")
            if os.path.exists(temp_passed):
                os.remove(temp_passed)
            sys.exit(1)

    # Constrain output to confirmation
    print("Total evaluated:", total_eval_runs)
    print("Passed this run:", len(passed_df))
    print("Newly appended:", newly_appended)
    print("Total rows in passed ledger:", total_rows_in_ledger)

if __name__ == "__main__":
    filter_strategies()
