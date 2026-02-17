import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
SERIES_PREFIX = "Range_Breakout02"

def load_data():
    all_trades = []
    for folder in BACKTESTS_ROOT.glob(f"{SERIES_PREFIX}_*"):
        csv_path = folder / "raw" / "results_tradelevel.csv"
        if not csv_path.exists(): continue
        
        try:
            df = pd.read_csv(csv_path)
            # Filter High Vol Only
            df = df[df['volatility_regime'] == 'high'].copy()
            if not df.empty:
                df['entry_timestamp'] = pd.to_datetime(df['entry_timestamp'])
                df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0.0)
                
                df['symbol'] = folder.name.replace(f"{SERIES_PREFIX}_", "")
                all_trades.append(df)
        except Exception:
            pass
            
    if not all_trades: return pd.DataFrame()
    master = pd.concat(all_trades, ignore_index=True)
    master = master.sort_values('entry_timestamp').reset_index(drop=True)
    return master

def compute_metrics(pnl_series):
    if pnl_series.empty:
        return {"Net Profit": 0.0, "PF": 0.0, "Sharpe": 0.0, "Max DD": 0.0}
        
    net = pnl_series.sum()
    
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    pf = wins / losses if losses > 0 else 999.0
    
    # DD
    cum = pnl_series.cumsum()
    peak = cum.cummax()
    dd = peak - cum
    max_dd = dd.max()
    
    # Sharpe (Trade-based)
    avg = pnl_series.mean()
    std = pnl_series.std()
    sharpe = (avg / std) * (len(pnl_series)**0.5) if std > 0 else 0
    
    return {
        "Net Profit": net,
        "PF": pf,
        "Sharpe": sharpe,
        "Max DD": max_dd
    }

def main():
    print("Distribution Audit (Range_Breakout02 High-Vol)")
    print("=" * 80)
    
    df = load_data()
    if df.empty:
        print("No trades found.")
        return
        
    total_trades = len(df)
    total_net_profit = df['pnl_usd'].sum()
    
    print(f"Total Trades: {total_trades}")
    print(f"Total Net Profit: ${total_net_profit:,.2f}")
    
    # --- PROCESSED PNL SERIES ---
    pnls = df['pnl_usd'].sort_values(ascending=False).values
    
    # 2. TOP 10 TRADES
    top_10_pnls = pnls[:10]
    top_10_sum = np.sum(top_10_pnls)
    top_10_pct = (top_10_sum / total_net_profit) * 100 if total_net_profit != 0 else 0
    
    # 3. TOP 5% TRADES
    n_top5 = int(total_trades * 0.05) if total_trades >= 20 else 1
    top_5pct_pnls = pnls[:n_top5]
    top_5pct_sum = np.sum(top_5pct_pnls)
    top_5pct_pct = (top_5pct_sum / total_net_profit) * 100 if total_net_profit != 0 else 0
    
    # 4. MEDIAN METRICS
    median_pnl = np.median(pnls)
    
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    
    avg_win = np.mean(wins) if len(wins) > 0 else 0.0
    avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0.0
    wl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    median_win = np.median(wins) if len(wins) > 0 else 0.0
    count_large_wins = np.sum(pnls > (2 * median_win))
    large_win_pct = (count_large_wins / total_trades) * 100
    
    print("-" * 80)
    print("Section A — Distribution Summary")
    print(f"{'Metric':<30} | {'Value':>15}")
    print("-" * 50)
    print(f"{'Total Net Profit':<30} | ${total_net_profit:,.2f}")
    print(f"{'Median Trade PnL':<30} | ${median_pnl:,.2f}")
    print(f"{'Avg Win':<30} | ${avg_win:,.2f}")
    print(f"{'Avg Loss':<30} | ${avg_loss:,.2f}")
    print(f"{'Win/Loss Ratio (Avg)':<30} | {wl_ratio:.2f}")
    print(f"{'% Trades > 2x Median Win':<30} | {large_win_pct:.1f}%")
    
    print("\nSection B — Concentration Analysis")
    print(f"{'Top 10 Contribution':<30} | ${top_10_sum:,.2f} ({top_10_pct:.1f}%)")
    print(f"{'Top 5% Contribution':<30} | ${top_5pct_sum:,.2f} ({top_5pct_pct:.1f}%)")
    
    # --- ROBUSTNESS TEST (Remove Top 10) ---
    print("\nSection C — Post-Removal Metrics (Robustness Test)")
    
    # Exclude Top 10 Winners
    # We sorted pnls descending, so pnls[10:] is the rest
    rob_pnls = pd.Series(pnls[10:])
    
    m_base = compute_metrics(df['pnl_usd'])
    m_rob = compute_metrics(rob_pnls)
    
    print("-" * 80)
    print(f"{'Metric':<15} | {'Baseline':>15} | {'After Removing Top 10':>25}")
    print("-" * 80)
    
    cols = ["Net Profit", "PF", "Sharpe", "Max DD"]
    for c in cols:
        v1 = m_base[c]
        v2 = m_rob[c]
        
        fmt = "${:,.2f}" if "Profit" in c or "DD" in c else "{:.2f}"
            
        print(f"{c:<15} | {fmt.format(v1):>15} | {fmt.format(v2):>25}")
        
    print("-" * 80)
    
    # Verdict
    # If PF drops below 1.2 or Net Profit becomes negative -> Fragile
    if m_rob['PF'] < 1.2 or m_rob['Net Profit'] < 0:
        verdict = "Fragile (Dependent on Outliers)"
    elif m_rob['PF'] < 1.4:
        verdict = "Moderately Concentrated"
    else:
        verdict = "Robust (Broad-Based Edge)"
        
    print(f"VERDICT: {verdict}")

    # --- ROBUSTNESS TEST (Directional) ---
    print("\nSection D — Directional Robustness (Bias Check)")
    print("Objective: Check if performance depends on a few large winners on either side.")
    
    if 'direction' in df.columns:
        longs = df[df['direction'] == 1].copy()
        shorts = df[df['direction'] == -1].copy()
    else:
        # Fallback to legacy logic if direction missing (unlikely now)
        longs = df[df['position_units'] > 0].copy()
        shorts = df[df['position_units'] < 0].copy()
    
    n_longs = len(longs)
    n_shorts = len(shorts)
    
    print(f"Total Longs: {n_longs}")
    print(f"Total Shorts: {n_shorts}")
    
    # Sort by PnL Descending
    longs_sorted = longs.sort_values('pnl_usd', ascending=False) if n_longs > 0 else pd.DataFrame()
    shorts_sorted = shorts.sort_values('pnl_usd', ascending=False) if n_shorts > 0 else pd.DataFrame()
    
    # Identify IDs to drop
    top20_long_idxs = longs_sorted.head(20).index if n_longs > 0 else []
    top20_short_idxs = shorts_sorted.head(20).index if n_shorts > 0 else []
    
    # Scenario 1: Remove Top 20 Longs
    if n_longs > 0:
        df_no_long_outliers = df.drop(top20_long_idxs)
        m_no_longs = compute_metrics(df_no_long_outliers['pnl_usd'])
    else:
        m_no_longs = m_base # No change
    
    # Scenario 2: Remove Top 20 Shorts
    if n_shorts > 0:
        df_no_short_outliers = df.drop(top20_short_idxs)
        m_no_shorts = compute_metrics(df_no_short_outliers['pnl_usd'])
    else:
        m_no_shorts = m_base # No change
    
    # Scenario 3: Remove Both
    to_drop = []
    if n_longs > 0: to_drop.extend(top20_long_idxs)
    if n_shorts > 0: to_drop.extend(top20_short_idxs)
    
    if to_drop:
        df_no_both = df.drop(to_drop)
        m_no_both = compute_metrics(df_no_both['pnl_usd'])
    else:
        m_no_both = m_base

    print("-" * 120)
    print(f"{'Metric':<15} | {'Baseline':>12} | {'- Top 20 Longs':>18} | {'- Top 20 Shorts':>18} | {'- Both':>18}")
    print("-" * 120)
    
    cols = ["Net Profit", "PF", "Sharpe", "Max DD"]
    for c in cols:
        v_base = m_base[c]
        v_no_long = m_no_longs[c]
        v_no_short = m_no_shorts[c]
        v_no_both = m_no_both[c]
        
        fmt = "${:,.2f}" if "Profit" in c or "DD" in c else "{:.2f}"
        
        # Helper for "N/A"
        s_long = fmt.format(v_no_long) if n_longs > 0 else "N/A"
        s_short = fmt.format(v_no_short) if n_shorts > 0 else "N/A"
        s_both = fmt.format(v_no_both) if (n_longs > 0 or n_shorts > 0) else "N/A"
        
        print(f"{c:<15} | {fmt.format(v_base):>12} | {s_long:>18} | {s_short:>18} | {s_both:>18}")
        
    print("-" * 120)
    
    # Verdict
    if n_longs == 0:
        print("DIRECTIONAL VERDICT: SHORT-ONLY BIAS (No Long Trades)")
    elif n_shorts == 0:
        print("DIRECTIONAL VERDICT: LONG-ONLY BIAS (No Short Trades)")
    else:
        long_survives = m_no_longs['PF'] > 1.25
        short_survives = m_no_shorts['PF'] > 1.25
        
        if long_survives and short_survives:
            print("DIRECTIONAL VERDICT: VERY STRONG (Both sides robust)")
        elif long_survives or short_survives:
            print("DIRECTIONAL VERDICT: CONDITIONAL BIAS (One side sensitive)")
        else:
            print("DIRECTIONAL VERDICT: FRAGILE (Both sides sensitive)")

if __name__ == "__main__":
    main()
