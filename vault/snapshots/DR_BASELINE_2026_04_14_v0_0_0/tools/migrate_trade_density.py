import pandas as pd
import numpy as np
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"

def migrate_strategy_sheets():
    sheets = [
        BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx",
        BACKTESTS_ROOT / "Filtered_Strategies_Passed.xlsx"
    ]
    for path in sheets:
        if not path.exists():
            print(f"Skipping {path.name} - not found.")
            continue
            
        print(f"Processing {path.name}...")
        df = pd.read_excel(path)
        
        # Calculate column
        density_values = []
        for idx, row in df.iterrows():
            try:
                tt = float(row.get("total_trades", 0))
                tp = float(row.get("trading_period", 365.25))
                if pd.isna(tt): tt = 0
                if pd.isna(tp) or tp <= 0: 
                    density_values.append("NA")
                    continue
                
                density = int(round(tt / (tp / 365.25)))
                density_values.append(density)
            except Exception as e:
                density_values.append("NA")
                
        # If it exists, remove it first
        if "trade_density" in df.columns:
            df = df.drop(columns=["trade_density"])
            
        # Re-insert dynamically after reference_capital_usd if it exists, otherwise total_trades
        if "total_trades" in df.columns:
            target_idx = df.columns.get_loc("total_trades") + 1
            df.insert(target_idx, "trade_density", density_values)
        else:
            df["trade_density"] = density_values
                
        df.to_excel(path, index=False)
        print(f"Saved {path.name} with {len(df)} rows.")


def migrate_portfolio_sheet():
    path = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"
    if not path.exists():
        print(f"Skipping {path.name} - not found.")
        return
        
    print(f"Processing {path.name}...")
    df = pd.read_excel(path)
    
    # Load strategy sheet to resolve timeframes
    master_strat = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
    strat_df = pd.DataFrame()
    if master_strat.exists():
        strat_df = pd.read_excel(master_strat)
        
    density_values = []
    for idx, row in df.iterrows():
        try:
            strat_id = str(row.get("source_strategy", ""))
            c_run_ids = str(row.get("constituent_run_ids", "")).split(",")
            c_run_ids = [r.strip() for r in c_run_ids if r.strip()]
            
            density = "NA"
            
            if c_run_ids and not strat_df.empty and 'run_id' in strat_df.columns and 'trade_density' in strat_df.columns:
                valid_density = strat_df[strat_df['run_id'].astype(str).isin(c_run_ids)]['trade_density']
                if not valid_density.empty and not valid_density.replace("NA", np.nan).isna().all():
                    clean_density = pd.to_numeric(valid_density, errors='coerce')
                    density = int(round(clean_density.dropna().sum()))
            
            # Fallback if constituents missing or density zeroed out
            if density == "NA" or density == 0:
                tt = float(row.get("total_trades", 0))
                if pd.isna(tt): tt = 0
                
                tp = None
                if not strat_df.empty and "strategy" in strat_df.columns:
                    match = strat_df[strat_df["strategy"].astype(str).str.startswith(strat_id)]
                    if not match.empty:
                        val = match.iloc[0].get("trading_period")
                        if pd.notnull(val):
                            tp = float(val)

                if tp and not pd.isna(tp) and tp > 0.1:
                    density = int(round(tt / (tp / 365.25)))
                    
            density_values.append(density)
        except Exception as e:
            print(f"Error on row {idx}: {e}")
            density_values.append("NA")
            
    # Remove existing
    if "trade_density" in df.columns:
        df = df.drop(columns=["trade_density"])
        
    # Re-insert immediately after reference_capital_usd
    if "reference_capital_usd" in df.columns:
        target_idx = df.columns.get_loc("reference_capital_usd") + 1
        df.insert(target_idx, "trade_density", density_values)
    else:
        df["trade_density"] = density_values
        
    df.to_excel(path, index=False)
    print(f"Saved {path.name} with {len(df)} rows.")

if __name__ == "__main__":
    migrate_strategy_sheets()
    migrate_portfolio_sheet()
    print("Migration complete.")
