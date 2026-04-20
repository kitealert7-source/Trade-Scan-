import pandas as pd
import numpy as np
from pathlib import Path

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
SERIES_PREFIX = "Range_Breakout02"

def calculate_sharpe(pnls):
    if not pnls: return 0.0
    # Assuming daily returns logic roughly, but here we have per-trade PnL.
    # Standard Sharpe usually requires periodic returns (daily/monthly).
    # We will approximate using trade PnL for now or reconstruction equity curve.
    # Better approach: Reconstruct Daily Equity Curve from trade timestamps.
    return 0.0 # Placeholder, logic below

def analyze_series():
    print(f"Validating High-Volatility Hypothesis for {SERIES_PREFIX}...")
    print("-" * 60)
    
    all_trades = []
    
    # 1. Harvest Trades
    for folder in BACKTESTS_ROOT.glob(f"{SERIES_PREFIX}_*"):
        csv_path = folder / "raw" / "results_tradelevel.csv"
        if not csv_path.exists():
            continue
            
        try:
            df = pd.read_csv(csv_path)
            # Ensure proper types
            df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0.0)
            df['exit_timestamp'] = pd.to_datetime(df['exit_timestamp'])
            
            # Filter High Vol
            df_high = df[df['volatility_regime'] == 'high'].copy()
            df_high['symbol'] = folder.name.replace(f"{SERIES_PREFIX}_", "")
            
            all_trades.append(df_high)
            
        except Exception as e:
            print(f"[WARN] Failed to read {folder.name}: {e}")

    if not all_trades:
        print("No trades found.")
        return

    # 2. Aggregation
    master_df = pd.concat(all_trades, ignore_index=True)
    master_df.sort_values("exit_timestamp", inplace=True)
    
    # 3. Metrics Calculation
    # Trade Count
    total_trades = len(master_df)
    
    # Profit Factor
    wins = master_df[master_df['pnl_usd'] > 0]['pnl_usd'].sum()
    losses = abs(master_df[master_df['pnl_usd'] < 0]['pnl_usd'].sum())
    pf = wins / losses if losses > 0 else float('inf')
    
    # Net PnL
    net_pnl = master_df['pnl_usd'].sum()
    
    # Drawdown (Portfolio Level)
    master_df['cumulative_pnl'] = master_df['pnl_usd'].cumsum()
    master_df['peak'] = master_df['cumulative_pnl'].cummax()
    master_df['dd'] = master_df['peak'] - master_df['cumulative_pnl']
    max_dd_usd = master_df['dd'].max()
    
    # Sharpe Ratio Approximation (Annualized)
    # We need Daily PnL
    master_df['date'] = master_df['exit_timestamp'].dt.date
    daily_pnl = master_df.groupby('date')['pnl_usd'].sum()
    
    # Reindex to full date range to account for flat days? 
    # For Sharpe, we usually want time-weighted.
    if not daily_pnl.empty:
        idx = pd.date_range(daily_pnl.index.min(), daily_pnl.index.max())
        daily_pnl = daily_pnl.reindex(idx, fill_value=0.0)
        
        avg_daily = daily_pnl.mean()
        std_daily = daily_pnl.std()
        sharpe = (avg_daily / std_daily) * (252**0.5) if std_daily > 0 else 0.0
    else:
        sharpe = 0.0

    print(f"Total Trades: {total_trades}")
    print(f"Net PnL: ${net_pnl:,.2f}")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Sharpe Ratio: {sharpe:.2f}")
    print(f"Max Drawdown: ${max_dd_usd:,.2f}")
    
    # --- DEEP DIVE ANALYSIS ---
    print("\n[DEEP DIVE] Symbol Distribution:")
    symbol_pnl = master_df.groupby('symbol')['pnl_usd'].sum().sort_values(ascending=False)
    for sym, pnl in symbol_pnl.items():
        print(f"  {sym:<10}: ${pnl:,.2f}")
        
    print("\n[DEEP DIVE] Year-by-Year Stability:")
    master_df['year'] = master_df['exit_timestamp'].dt.year
    yearly_pnl = master_df.groupby('year')['pnl_usd'].sum().sort_index()
    for yr, pnl in yearly_pnl.items():
        print(f"  {yr}: ${pnl:,.2f}")
        
    print("\n[DEEP DIVE] Tail Risk (High-Vol Subset):")
    # Worst 5 Loss %
    # = (Sum of Worst 5 Losses) / Gross Loss
    high_vol_losses = master_df[master_df['pnl_usd'] < 0]['pnl_usd'].tolist()
    high_vol_losses.sort() # ascending (most negative first)
    
    gross_loss = abs(sum(high_vol_losses))
    worst_5_sum = sum(high_vol_losses[:5]) if len(high_vol_losses) >= 5 else sum(high_vol_losses)
    
    if gross_loss > 0:
        w5_pct = (abs(worst_5_sum) / gross_loss) * 100
    else:
        w5_pct = 0.0
        
    print(f"  Gross Loss: ${gross_loss:,.2f}")
    print(f"  Worst 5 Losses Sum: ${worst_5_sum:,.2f}")
    print(f"  Worst 5 Loss %: {w5_pct:.2f}%")
    
    # Longest Loss Streak
    max_streak = 0
    curr_streak = 0
    # Provide temporal ordering
    sorted_pnls = master_df.sort_values('exit_timestamp')['pnl_usd'].tolist()
    for p in sorted_pnls:
        if p < 0:
            curr_streak += 1
            if curr_streak > max_streak:
                max_streak = curr_streak
        else:
            curr_streak = 0
            
    print(f"  Longest Loss Streak: {max_streak}")

    print("-" * 60)
    print("HYPOTHESIS CHECK:")
    pass_pf = pf > 1.3
    pass_sharpe = sharpe > 0.7
    
    # Additional Checks?
    # Structural Edge: If > 50% of symbols are profitable
    profitable_syms = (symbol_pnl > 0).sum()
    total_syms = len(symbol_pnl)
    sym_participation = profitable_syms / total_syms if total_syms > 0 else 0
    print(f"Symbol Participation: {profitable_syms}/{total_syms} ({sym_participation:.1%})")
    
    # Stability: If > 50% of years are profitable (or no massive blowout year that accounts for 100% of profit)
    profitable_years = (yearly_pnl > 0).sum()
    total_years = len(yearly_pnl)
    # Check if a single year accounts for > 80% of profit?
    max_year_profit = yearly_pnl.max()
    concentration_risk = (max_year_profit / net_pnl) if net_pnl > 0 else 0.0
    print(f"Yearly Stability: {profitable_years}/{total_years} profitable")
    print(f"Max Year Concentration: {concentration_risk:.1%}")

    print("-" * 60)
    
    print(f"PF > 1.3: {'PASS' if pass_pf else 'FAIL'}")
    print(f"Sharpe > 0.7: {'PASS' if pass_sharpe else 'FAIL'}")
    
    if pass_pf and pass_sharpe:
        print("=> High-vol breakout IS VIABLE.")
    else:
        print("=> Criteria NOT met.")

if __name__ == "__main__":
    analyze_series()
