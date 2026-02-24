import pandas as pd
from pathlib import Path
import sys

# Config
BACKTESTS_ROOT = Path("backtests")
STRATEGIES_ROOT = Path("strategies")

def check_csv_schema(path):
    print(f"\n--- Auditing {path} ---")
    if not path.exists():
        print("[FAIL] File not found.")
        return
    
    try:
        df = pd.read_csv(path)
        print(f"Columns: {list(df.columns)}")
        
        mandatory = ["volatility_regime", "trend_score", "trend_regime", "trend_label"]
        missing = [c for c in mandatory if c not in df.columns]
        
        if missing:
            print(f"[FAIL] Missing mandatory columns: {missing}")
        else:
            print("[PASS] Mandatory market state fields present.")
            
        # Check for nulls in mandatory fields
        for col in mandatory:
            if col in df.columns:
                nulls = df[col].isnull().sum()
                if nulls > 0:
                     print(f"[FAIL] Null values found in {col}: {nulls}")
                else:
                     print(f"[PASS] No nulls in {col}.")
                     
        # Check unique values for regime to ensure no legacy logic
        if "volatility_regime" in df.columns:
            print(f"Unique Volatility Regimes: {df['volatility_regime'].unique()}")
            
    except Exception as e:
        print(f"[ERROR] {e}")

def check_excel_schema(path, sheet_name=None):
    print(f"\n--- Auditing {path} [{'Sheet: ' + sheet_name if sheet_name else 'First Sheet'}] ---")
    if not path.exists():
        print(f"[FAIL] File not found: {path}")
        return

    try:
        if sheet_name:
            df = pd.read_excel(path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(path)
            
        print(f"Columns: {list(df.columns)}")
        return df
    except Exception as e:
        print(f"[ERROR] {e}")
        return None

def main():
    
    # ---------------------------------------------------------
    # STRICT SCHEMA DEFINITIONS (SOP v4.2)
    # ---------------------------------------------------------
    SOP_CSV_COLS = {
        "strategy_name", "parent_trade_id", "sequence_index", 
        "entry_timestamp", "exit_timestamp", "direction", 
        "entry_price", "exit_price", "pnl_usd", "r_multiple", 
        "trade_high", "trade_low", "bars_held", "atr_entry", 
        "position_units", "notional_usd", "mfe_price", "mae_price", 
        "mfe_r", "mae_r", "volatility_regime", "trend_score", 
        "trend_regime", "trend_label"
    }

    SOP_MASTER_COLS = {
        "run_id", "strategy", "symbol", "timeframe", 
        "test_start", "test_end", "trading_period", 
        "total_trades", "total_net_profit", "gross_profit", "gross_loss", 
        "profit_factor", "expectancy", "sharpe_ratio", 
        "max_drawdown", "max_dd_pct", "return_dd_ratio", 
        "worst_5_loss_pct", "longest_loss_streak", 
        "pct_time_in_market", "avg_bars_in_trade",
        
        # Volatility Breakdown
        "net_profit_high_vol", "net_profit_normal_vol", "net_profit_low_vol",
        
        # Trend Breakdown (Expected)
        "net_profit_strong_up", "net_profit_weak_up", "net_profit_neutral", 
        "net_profit_weak_down", "net_profit_strong_down",
        "trades_strong_up", "trades_weak_up", "trades_neutral", 
        "trades_weak_down", "trades_strong_down",
        
        # Governance
        "IN_PORTFOLIO"
    }

    # 1. results_tradelevel.csv (Representative)
    # Finding a valid run
    run_folders = [f for f in BACKTESTS_ROOT.iterdir() if f.is_dir() and not f.name.startswith(".")]
    if not run_folders:
        print("[FAIL] No run folders found.")
        return
    
    target_run = run_folders[0] # Pick first one
    print(f"Targeting Run: {target_run.name}")
    
    csv_path = target_run / "raw" / "results_tradelevel.csv"
    if csv_path.exists():
        check_csv_schema(csv_path)
        # Extra Check
        try:
            df = pd.read_csv(csv_path)
            found = set(df.columns)
            extra = found - SOP_CSV_COLS
            if extra:
                print(f"[WARN] Extra columns in CSV (Outside SOP): {extra}")
            else:
                print("[PASS] CSV strict adherence (No extra columns).")
        except Exception: pass
    
    # 2. Stage-2 Excel (Trades List)
    report_files = list(target_run.glob("AK_Trade_Report_*.xlsx"))
    if not report_files:
        print("[FAIL] AK_Trade_Report not found.")
    else:
        check_excel_schema(report_files[0], sheet_name="Trades List")
        
        # Check Settings for Version
        settings_df = check_excel_schema(report_files[0], sheet_name="Settings")
        if settings_df is not None:
             print("\n--- Settings Version Check ---")
             # Settings usually has Parameter, Value cols.
             if "Parameter" in settings_df.columns:
                 ver_row = settings_df[settings_df["Parameter"] == "Engine Version"]
                 if not ver_row.empty:
                     print(f"Engine Version: {ver_row['Value'].values[0]}")
                 else:
                     print("[FAIL] Engine Version parameter not found.")
                     
                 schema_row = settings_df[settings_df["Parameter"] == "Schema Version"]
                 if not schema_row.empty:
                     print(f"Schema Version: {schema_row['Value'].values[0]}")
                 else:
                     print("[FAIL] Schema Version parameter not found.")

    # 3. Strategy_Master_Filter.xlsx
    master_filter = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
    df_master = check_excel_schema(master_filter)
    
    if df_master is not None:
        found_master = set(df_master.columns)
        
        # Trend Check
        trend_cols = [
            "net_profit_strong_up", "net_profit_weak_up", "net_profit_neutral", 
            "net_profit_weak_down", "net_profit_strong_down",
            "trades_strong_up", "trades_weak_up", "trades_neutral", 
            "trades_weak_down", "trades_strong_down"
        ]
        missing_trend = [c for c in trend_cols if c not in df_master.columns]
        if missing_trend:
            print(f"[FAIL] Missing Trend Breakdown columns in Master Filter: {missing_trend}")
        else:
             print("[PASS] Trend Breakdown columns present.")
        
        # Vol Check
        vol_cols = ["net_profit_high_vol", "net_profit_normal_vol", "net_profit_low_vol"]
        missing_vol = [c for c in vol_cols if c not in df_master.columns]
        if missing_vol:
            print(f"[FAIL] Missing Volatility Breakdown columns in Master Filter: {missing_vol}")
        else:
            print("[PASS] Volatility Breakdown columns present.")
            
        # EXTRA Check
        extra_master = found_master - SOP_MASTER_COLS
        if extra_master:
            print(f"[WARN] Extra columns in Master Filter (Outside SOP): {extra_master}")
        else:
            print("[PASS] Master Filter strict adherence (No extra columns).")

    # 4. Master_Portfolio_Sheet.xlsx
    portfolio_sheet = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"
    check_excel_schema(portfolio_sheet)

if __name__ == "__main__":
    main()
