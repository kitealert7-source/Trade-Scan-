import pandas as pd
import numpy as np
from pathlib import Path

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
SERIES_PREFIX = "Range_Breakout02"

def compute_metrics(pnl_series: pd.Series):
    if pnl_series.empty:
        return {"Net Profit": 0.0, "PF": 0.0, "Sharpe": 0.0, "Max DD": 0.0, "Win Rate": 0.0}
        
    net_profit = pnl_series.sum()
    wins = pnl_series[pnl_series > 0]
    losses = pnl_series[pnl_series <= 0]
    
    gross_win = wins.sum()
    gross_loss = abs(losses.sum())
    
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    
    # Sharpe (approx per trade) - using variance of Trade PnL
    # Not time weighted but good enough for robustness relative comparison
    mean = pnl_series.mean()
    std = pnl_series.std()
    sharpe = mean / std if std > 0 else 0.0 
    
    # Max DD (Portfolio view of just this series)
    equity = pnl_series.cumsum()
    peak = equity.cummax()
    dd = peak - equity
    max_dd = dd.max()
    
    win_rate = len(wins) / len(pnl_series) if len(pnl_series) > 0 else 0.0
    
    return {
        "Net Profit": net_profit,
        "PF": pf,
        "Sharpe": sharpe,
        "Max DD": max_dd,
        "Win Rate": win_rate
    }

def main():
    print(f"FINAL AUDIT: High-Volatility Subset for {SERIES_PREFIX}")
    print("-" * 60)
    
    all_trades = []
    
    # 1. Harvest Trades
    print("Harvesting trades from backtests...")
    for folder in BACKTESTS_ROOT.glob(f"{SERIES_PREFIX}_*"):
        # Skip debug folder
        if "DEBUG" in folder.name: continue
        
        csv_path = folder / "raw" / "results_tradelevel.csv"
        if not csv_path.exists():
            continue
            
        try:
            df = pd.read_csv(csv_path)
            # Ensure proper types
            df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0.0)
            df['direction'] = pd.to_numeric(df['direction'], errors='coerce').fillna(1)
            
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
    df = pd.concat(all_trades, ignore_index=True)
    # Sort by pnl for outlier removal (though usually done per robustness check)
    
    n_total = len(df)
    print(f"Total High-Vol Trades: {n_total}")
    
    # --- DISTRIBUTION AUDIT ---
    
    # A. Concentration
    print("\nSection A — Concentration Analysis")
    df_sorted = df.sort_values("pnl_usd", ascending=False)
    total_profit = df['pnl_usd'].sum()
    
    top10 = df_sorted.head(10)
    top10_sum = top10['pnl_usd'].sum()
    
    n_5pct = int(n_total * 0.05)
    top5pct = df_sorted.head(n_5pct)
    top5pct_sum = top5pct['pnl_usd'].sum()
    
    print(f"Total Net Profit: ${total_profit:,.2f}")
    print(f"Top 10 Trades Sum: ${top10_sum:,.2f} ({(top10_sum/total_profit):.1%})")
    print(f"Top 5% Trades Sum: ${top5pct_sum:,.2f} ({(top5pct_sum/total_profit):.1%})")
    
    # B. Robustness (Removal)
    print("\nSection B — Robustness Checks (Outlier Removal)")
    
    m_base = compute_metrics(df['pnl_usd'])
    
    # Remove Top 10
    df_no_top10 = df_sorted.iloc[10:]
    m_no_top10 = compute_metrics(df_no_top10['pnl_usd'])
    
    # Remove Top 5%
    df_no_top5pct = df_sorted.iloc[n_5pct:]
    m_no_top5pct = compute_metrics(df_no_top5pct['pnl_usd'])
    
    print(f"{'Metric':<15} | {'Baseline':>12} | {'- Top 10':>12} | {'- Top 5%':>12}")
    print("-" * 60)
    
    cols = ["Net Profit", "PF", "Sharpe", "Max DD"]
    for c in cols:
        v_base = m_base[c]
        v_no10 = m_no_top10[c]
        v_no5p = m_no_top5pct[c]
        
        fmt = "${:,.2f}" if "Profit" in c or "DD" in c else "{:.2f}"
        print(f"{c:<15} | {fmt.format(v_base):>12} | {fmt.format(v_no10):>12} | {fmt.format(v_no5p):>12}")
        
    print("-" * 60)
    
    # C. Directional Check
    print("\nSection C — Directional Robustness")
    
    if 'direction' in df.columns:
        longs = df[df['direction'] == 1].copy()
        shorts = df[df['direction'] == -1].copy()
    else:
        # Fallback (Verified incorrect but kept for safety if col missing)
        longs = df[df['position_units'] > 0].copy() # Should filter differently if logic was old
        shorts = df[df['position_units'] < 0].copy()
    
    n_longs = len(longs)
    n_shorts = len(shorts)
    
    print(f"Long Trades: {n_longs}")
    print(f"Short Trades: {n_shorts}")
    
    # Sort separately
    longs_sorted = longs.sort_values('pnl_usd', ascending=False)
    shorts_sorted = shorts.sort_values('pnl_usd', ascending=False)
    
    # Remove Top 20 Each
    df_no_long20 = df.drop(longs_sorted.head(20).index)
    m_no_long20 = compute_metrics(df_no_long20['pnl_usd'])
    
    df_no_short20 = df.drop(shorts_sorted.head(20).index)
    m_no_short20 = compute_metrics(df_no_short20['pnl_usd'])
    
    # Remove Both Top 20
    to_drop = []
    to_drop.extend(longs_sorted.head(20).index.tolist())
    to_drop.extend(shorts_sorted.head(20).index.tolist())
    df_no_both20 = df.drop(to_drop)
    m_no_both20 = compute_metrics(df_no_both20['pnl_usd'])
    
    print(f"{'Metric':<15} | {'Baseline':>12} | {'- Top 20 Long':>15} | {'- Top 20 Short':>15} | {'- Both':>15}")
    print("-" * 80)
    
    for c in cols:
        v_base = m_base[c]
        v_nl = m_no_long20[c]
        v_ns = m_no_short20[c]
        v_nb = m_no_both20[c]
        
        fmt = "${:,.2f}" if "Profit" in c or "DD" in c else "{:.2f}"
        print(f"{c:<15} | {fmt.format(v_base):>12} | {fmt.format(v_nl):>15} | {fmt.format(v_ns):>15} | {fmt.format(v_nb):>15}")
        
    print("-" * 80)
    
    # VERDICT
    print("\nFINAL VERDICT:")
    if n_longs > 0 and n_shorts > 0:
        pf_long_resid = m_no_long20['PF']
        pf_short_resid = m_no_short20['PF']
        
        if pf_long_resid > 1.25 and pf_short_resid > 1.25:
            print(">> ROBUST & BALANCED. Both sides perform well even after filtering top winners.")
        elif pf_long_resid < 1.1 or pf_short_resid < 1.1:
            print(">> FRAGILE. Removing outliers breaks potential profitability on one or both sides.")
        else:
            print(">> ACCEPTABLE. Performance holds but bias may exist.")
            
        print(f"   Long Residual PF: {pf_long_resid:.2f}")
        print(f"   Short Residual PF: {pf_short_resid:.2f}")
    else:
        print(">> BIASED. One direction has 0 trades.")

if __name__ == "__main__":
    main()
