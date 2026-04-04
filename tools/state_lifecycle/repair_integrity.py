import sys
import argparse
import pandas as pd
from pathlib import Path

STATE_ROOT = Path(__file__).resolve().parents[2].parent / "TradeScan_State"
MASTER_SHEET_PATH = STATE_ROOT / "strategies" / "Master_Portfolio_Sheet.xlsx"
FILTERED_SHEET_PATH = STATE_ROOT / "candidates" / "Filtered_Strategies_Passed.xlsx"

RUNS_DIR = STATE_ROOT / "runs"
BACKTESTS_DIR = STATE_ROOT / "backtests"
SANDBOX_DIR = STATE_ROOT / "sandbox"

def is_valid_run(run_id: str) -> bool:
    r_str = str(run_id).strip()
    if not r_str or r_str.lower() == "nan":
        return False
        
    t_run = RUNS_DIR / r_str
    t_sand = SANDBOX_DIR / r_str
    
    # Check folder footprints
    folder_valid = t_run.exists() or t_sand.exists()
    
    # Check json artifact footprints natively
    regular_json = BACKTESTS_DIR / f"{r_str}.json"
    local_run_json = t_run / "run_state.json"
    sandbox_json = t_sand / "run_state.json"
    
    json_valid = regular_json.exists() or local_run_json.exists() or sandbox_json.exists()
    
    return folder_valid and json_valid


def main():
    parser = argparse.ArgumentParser(description="Diagnose and gracefully repair state spreadsheet integrity.")
    parser.add_argument("--action", choices=["drop", "mark"], default="drop", help="Action to take when a footprint is missing.")
    parser.add_argument("--dry-run", action="store_true", help="Diagnose and report only without performing any physical disk mutations.")
    args = parser.parse_args()
    
    mode_str = f"{args.action.upper()} MODE - DRY RUN" if args.dry_run else f"{args.action.upper()} MODE"
    print(f"--- Phase 0: Diagnose & Repair Referential Integrity ({mode_str}) ---")
    
    # 1. Load Data
    try:
        df_master = pd.read_excel(MASTER_SHEET_PATH)
        df_filtered = pd.read_excel(FILTERED_SHEET_PATH)
    except Exception as e:
        print(f"[FAIL] Could not load spreadsheets: {e}")
        sys.exit(1)
        
    missing_in_filtered = set()
    missing_in_master = set()
    
    portfolio_issues = {} # portfolio_id -> {"missing_count": int, "removed": list}

    # 2. Diagnose & Repair Filtered
    print("\nScanning Filtered Strategies...")
    original_filtered_count = len(df_filtered)
    valid_filtered_indices = []
    
    for idx, row in df_filtered.iterrows():
        rid = str(row.get("run_id", "")).strip()
        if not is_valid_run(rid):
            missing_in_filtered.add(rid)
            if args.action == "mark":
                # Ensure validation_status col exists
                if "validation_status" not in df_filtered.columns:
                    df_filtered["validation_status"] = "OK"
                df_filtered.at[idx, "validation_status"] = "MISSING"
                valid_filtered_indices.append(idx)
        else:
            if "validation_status" in df_filtered.columns:
                df_filtered.at[idx, "validation_status"] = "OK"
            valid_filtered_indices.append(idx)
            
    df_filtered_repaired = df_filtered.loc[valid_filtered_indices].copy()
    
    # 3. Diagnose & Repair Master
    print("Scanning Master Portfolio Sheet...")
    repaired_master_rows = []
    
    for idx, row in df_master.iterrows():
        port_id = str(row.get("portfolio_id", "")).strip()
        constituents_str = str(row.get("constituent_run_ids", "")).strip()
        
        if not port_id or port_id.lower() == "nan":
            repaired_master_rows.append(row)
            continue
            
        if not constituents_str or constituents_str.lower() == "nan":
            repaired_master_rows.append(row)
            continue
            
        c_list = [c.strip() for c in constituents_str.split(",") if c.strip()]
        valid_c = []
        missing_c = []
        
        for c in c_list:
            if is_valid_run(c):
                valid_c.append(c)
            else:
                missing_c.append(c)
                missing_in_master.add(c)
                if args.action == "mark":
                    valid_c.append(f"[MISSING] {c}")
                
        if missing_c:
            portfolio_issues[port_id] = {
                "missing_count": len(missing_c),
                "removed_ids": missing_c,
                "original_count": len(c_list),
                "remaining_count": len([x for x in valid_c if not x.startswith("[MISSING]")])
            }
            
        row["constituent_run_ids"] = ",".join(valid_c)
        repaired_master_rows.append(row)
        
    df_master_repaired = pd.DataFrame(repaired_master_rows)
    
    # Check invalid portfolios
    portfolios_to_drop = []
    for pid, data in portfolio_issues.items():
        if data["remaining_count"] == 0:
            portfolios_to_drop.append(pid)
            
    if portfolios_to_drop and args.action == "drop":
        df_master_repaired = df_master_repaired[~df_master_repaired["portfolio_id"].isin(portfolios_to_drop)]
    elif portfolios_to_drop and args.action == "mark":
        if "validation_status" not in df_master_repaired.columns:
            df_master_repaired["validation_status"] = "OK"
        # Mark entire portfolio as missing
        mask = df_master_repaired["portfolio_id"].isin(portfolios_to_drop)
        df_master_repaired.loc[mask, "validation_status"] = "INVALIDATED"

    # 4. output Report
    print("\n================ DIAGNOSTIC REPORT ================")
    print(f"[NON-CRITICAL] Filtered Sheet Run Drops: {len(missing_in_filtered)}")
    print(f"[CRITICAL] Master Sheet Run Drops:       {len(missing_in_master)}")
    
    if portfolio_issues:
        print("\n--- AFFECTED PORTFOLIOS ---")
        for pid, data in portfolio_issues.items():
            flag = "[FLAG: INVALIDATED - 0 CONSTITUENTS]" if data["remaining_count"] == 0 else "[REPAIRED]"
            print(f"- {pid}: {flag}")
            print(f"    Missing runs: {data['missing_count']} / {data['original_count']} original")
    else:
        print("\nNo portfolios affected.")
        
    # 5. Save disk
    if args.dry_run:
        print("\n================ DRY RUN SUMMARY ================")
        print(f"[HALT] Executed safely in DRY RUN mode. The following actions WOULD be taken:")
        print(f"  - {FILTERED_SHEET_PATH.name}: Drop {original_filtered_count - len(df_filtered_repaired)} rows")
        print(f"  - {MASTER_SHEET_PATH.name}: Drop {len(portfolios_to_drop)} dead portfolios")
        print("\nNo physical files were mutated.")
        return
        
    print("\n================ REPAIR EXECUTION ================")
    df_filtered_repaired.to_excel(FILTERED_SHEET_PATH, index=False)
    print(f"-> Repaired {FILTERED_SHEET_PATH.name} (Dropped {original_filtered_count - len(df_filtered_repaired)} rows)")
    
    df_master_repaired.to_excel(MASTER_SHEET_PATH, index=False)
    print(f"-> Repaired {MASTER_SHEET_PATH.name} (Dropped {len(portfolios_to_drop)} dead portfolios)")
    
    print("\n[SUCCESS] Referential Integrity Restored. Spreadsheets active and valid.")

if __name__ == "__main__":
    main()
