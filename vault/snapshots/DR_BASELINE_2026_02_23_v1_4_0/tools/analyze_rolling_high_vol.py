import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta
import calendar

PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
SERIES_PREFIX = "Range_Breakout02"

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year,month)[1])
    return pd.Timestamp(year, month, day)

def compute_metrics(trades_df):
    if trades_df.empty:
        return {
            "Net Profit": 0.0,
            "PF": 0.0,
            "Sharpe": 0.0,
            "Max DD": 0.0,
            "Trades": 0
        }
        
    # Net Profit
    net_pnl = trades_df['pnl_usd'].sum()
    
    # PF
    wins = trades_df[trades_df['pnl_usd'] > 0]['pnl_usd'].sum()
    losses = abs(trades_df[trades_df['pnl_usd'] < 0]['pnl_usd'].sum())
    pf = wins / losses if losses > 0 else float('inf')
    
    # Max DD (Intraday approx from trade sequence)
    # Sort by exit time
    trades_df = trades_df.sort_values('exit_timestamp')
    cumulative = trades_df['pnl_usd'].cumsum()
    peak = cumulative.cummax()
    dd = peak - cumulative
    max_dd = dd.max()
    
    # Sharpe (Annualized Daily Returns)
    # Reconstruct daily PnL
    trades_df['date'] = trades_df['exit_timestamp'].dt.date
    daily_pnl = trades_df.groupby('date')['pnl_usd'].sum()
    
    # We need a continuous daily index for the window duration to catch flat days?
    # Or just use the days traded? Standard practice varies. 
    # For robust Sharpe, we should fill 0s for non-trading days in the period? 
    # Let's use traded days for now to avoid zero-variance issues if sparse.
    # Actually, Sharpe assumes periodic returns. 
    # Let's perform standard calc on available daily data points.
    if len(daily_pnl) > 1:
        avg_daily = daily_pnl.mean()
        std_daily = daily_pnl.std()
        sharpe = (avg_daily / std_daily) * (252**0.5) if std_daily > 0 else 0.0
    else:
        sharpe = 0.0
        
    return {
        "Net Profit": net_pnl,
        "PF": pf,
        "Sharpe": sharpe,
        "Max DD": max_dd,
        "Trades": len(trades_df)
    }

def main():
    print(f"Rolling 6-Month High-Vol Analysis for {SERIES_PREFIX}...")
    print("=" * 80)
    
    all_trades = []
    
    # 1. Load Data
    for folder in BACKTESTS_ROOT.glob(f"{SERIES_PREFIX}_*"):
        csv_path = folder / "raw" / "results_tradelevel.csv"
        if not csv_path.exists(): continue
        
        try:
            df = pd.read_csv(csv_path)
            # Filter High Vol
            df = df[df['volatility_regime'] == 'high'].copy()
            
            if not df.empty:
                df['exit_timestamp'] = pd.to_datetime(df['exit_timestamp'])
                df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0.0)
                all_trades.append(df)
        except Exception as e:
            print(f"[WARN] Failed to read {folder.name}: {e}")
            
    if not all_trades:
        print("No high-volatility trades found.")
        return

    master_df = pd.concat(all_trades, ignore_index=True)
    master_df = master_df.sort_values('exit_timestamp')
    
    start_date = master_df['exit_timestamp'].min().normalize()
    end_date = master_df['exit_timestamp'].max().normalize()
    
    print(f"Data Range: {start_date.date()} to {end_date.date()}")
    print("-" * 80)
    print(f"{'Window Start':<12} | {'Window End':<12} | {'Net Profit':>12} | {'PF':>6} | {'Sharpe':>6} | {'Max DD':>10} | {'Trades':>6}")
    print("-" * 80)
    
    cumulative_results = []
    
    current_start = start_date
    window_months = 6
    
    while True:
        current_end = add_months(current_start, window_months)
        if current_start > end_date:
            break
            
        # Filter Window
        # [Start, End)
        window_df = master_df[
            (master_df['exit_timestamp'] >= current_start) & 
            (master_df['exit_timestamp'] < current_end)
        ]
        
        # We only care if the window actually overlaps with data range significantly?
        # User said "Rolling 6-month". 
        # If window_end is beyond last data, it's a partial window?
        # Usually we stop when window_start is close to end_date.
        # Let's include it if there's data.
        
        metrics = compute_metrics(window_df)
        
        print(f"{str(current_start.date()):<12} | {str(current_end.date()):<12} | "
              f"{metrics['Net Profit']:>12.2f} | {metrics['PF']:>6.2f} | {metrics['Sharpe']:>6.2f} | "
              f"{metrics['Max DD']:>10.2f} | {metrics['Trades']:>6}")
        
        metrics['Window Start'] = current_start
        metrics['Window End'] = current_end
        cumulative_results.append(metrics)
        
        # Step 1 Month
        current_start = add_months(current_start, 1)

    print("-" * 80)
    
    # Summary Stats
    results_df = pd.DataFrame(cumulative_results)
    
    if results_df.empty:
        print("No windows generated.")
        return

    worst_net = results_df.loc[results_df['Net Profit'].idxmin()]
    worst_pf = results_df.loc[results_df['PF'].idxmin()]
    worst_sharpe = results_df.loc[results_df['Sharpe'].idxmin()]
    worst_dd = results_df.loc[results_df['Max DD'].idxmax()] # Max DD is positive number usually, but here we want largest DD
    
    neg_windows = len(results_df[results_df['Net Profit'] < 0])
    
    print("\nWORST CASE SCENARIOS:")
    print(f"Worst Net Profit Window: ${worst_net['Net Profit']:.2f} ({worst_net['Window Start'].date()} - {worst_net['Window End'].date()})")
    print(f"Worst PF Window:         {worst_pf['PF']:.2f}")
    print(f"Worst Sharpe Window:     {worst_sharpe['Sharpe']:.2f}")
    print(f"Worst Max DD Window:     ${worst_dd['Max DD']:.2f}")
    print(f"Negative Windows:        {neg_windows} / {len(results_df)} ({neg_windows/len(results_df):.1%})")
    print("-" * 80)

if __name__ == "__main__":
    main()
