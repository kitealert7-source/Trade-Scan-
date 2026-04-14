import pandas as pd
import numpy as np
from pathlib import Path
import random

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
            if not df.empty:
                df['entry_timestamp'] = pd.to_datetime(df['entry_timestamp'])
                df['exit_timestamp'] = pd.to_datetime(df['exit_timestamp'])
                df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0.0)
                
                # We need ATR for rolling calc
                if 'atr_entry' in df.columns:
                    df['atr_entry'] = pd.to_numeric(df['atr_entry'], errors='coerce').fillna(0.0)
                else:
                    df['atr_entry'] = 0.0 # Will break rolling calc if missing
                    
                df['symbol'] = folder.name.replace(f"{SERIES_PREFIX}_", "")
                all_trades.append(df)
        except Exception:
            pass
            
    if not all_trades: return pd.DataFrame()
    master = pd.concat(all_trades, ignore_index=True)
    master = master.sort_values('entry_timestamp').reset_index(drop=True)
    return master

def compute_metrics(trades_df):
    if trades_df.empty:
        return {"Net Profit": 0, "PF": 0, "Sharpe": 0, "Max DD": 0, "Trades": 0}
        
    net = trades_df['pnl_usd'].sum()
    wins = trades_df[trades_df['pnl_usd'] > 0]['pnl_usd'].sum()
    losses = abs(trades_df[trades_df['pnl_usd'] < 0]['pnl_usd'].sum())
    pf = wins / losses if losses > 0 else 999.0
    
    # DD
    cum = trades_df['pnl_usd'].cumsum()
    peak = cum.cummax()
    dd = peak - cum
    max_dd = dd.max()
    
    # Sharpe (Trade-based approx)
    # Average trade / Std Dev * sqrt(trades)
    avg = trades_df['pnl_usd'].mean()
    std = trades_df['pnl_usd'].std()
    sharpe = (avg / std) * (len(trades_df)**0.5) if std > 0 else 0
    # Note: annualized Sharpe is better but trade-based is okay for comparative relative test
    
    return {
        "Net Profit": net,
        "PF": pf,
        "Sharpe": sharpe,
        "Max DD": max_dd,
        "Trades": len(trades_df)
    }

def test_rolling_vol(df):
    print("\n[TEST 1] Volatility Lag Test (Rolling History only)...")
    
    # We need to simulate the rolling classification.
    # Method: Expanding Window.
    # For each trade i, compute percentiles of atr_entry[0...i-1].
    # Classify trade i.
    
    # We can do this vectorized? Or loop?
    # Loop is safer to be exact.
    
    # We need a list of (atr, pnl, timestamp)
    # Sort by time.
    
    # Global or Per-Symbol?
    # Original logic: Per Symbol or Global?
    # `execution_emitter_stage1.py` computes it per-run (per symbol).
    # So we must do it Per Symbol!
    
    refined_trades = []
    
    for sym, group in df.groupby('symbol'):
        group = group.sort_values('entry_timestamp').copy()
        atrs = group['atr_entry'].values
        
        # We need at least some history to define percentiles.
        # Let's say N=20 startup.
        # Before N=20, we can't classify reliably. Skip or assume Normal?
        # Let's Skip first 20 for fairness unless original didn't.
        # Or Just use "Default Normal".
        
        regimes = []
        lagged_regimes = [] # Shifted by 1
        
        history = []
        
        # DEBUG: Print first few ATRs
        # if sym == "AUDNZD": print(f"DEBUG {sym} ATRs: {atrs[:5]}")
        
        for i in range(len(atrs)):
            curr_atr = atrs[i]
            
            # Check for valid ATR
            if curr_atr == 0:
                regimes.append("normal")
                if i > 0: lagged_regimes.append(regimes[i-1])
                else: lagged_regimes.append("normal")
                history.append(curr_atr)
                continue
            
            if len(history) < 20:
                regime = "normal" # Default
            else:
                p33 = np.percentile(history, 33)
                p66 = np.percentile(history, 66)
                
                if sym == "AUDNZD" and i % 50 == 0:
                    print(f"DEBUG {i}: ATR={curr_atr:.5f} vs P33={p33:.5f}|P66={p66:.5f}")
                
                if curr_atr <= p33: regime = "low"
                elif curr_atr <= p66: regime = "normal"
                else: regime = "high"
            
            regimes.append(regime)
            
            # Lagged: What was the regime of the PREVIOUS trade?
            # Persistence test.
            if i > 0:
                lagged_regimes.append(regimes[i-1]) # Use previous classification
            else:
                lagged_regimes.append("normal")
                
            history.append(curr_atr)
            
        group['rolling_regime'] = regimes
        group['lagged_regime'] = lagged_regimes
        refined_trades.append(group)
        
    refined_df = pd.concat(refined_trades, ignore_index=True)
    refined_df = refined_df.sort_values('entry_timestamp')
    
    # 1. Rolling High Vol
    rolling_high = refined_df[refined_df['rolling_regime'] == 'high']
    m_roll = compute_metrics(rolling_high)
    
    # 2. Lagged High Vol
    lagged_high = refined_df[refined_df['lagged_regime'] == 'high']
    m_lag = compute_metrics(lagged_high)
    
    # 3. Original Baseline (Full Sample Lookahead)
    # We can perform the original check here too if 'volatility_regime' column exists in input?
    # The input CSV has 'volatility_regime' computed by Stage 1 (Full Sample).
    orig_high = df[df['volatility_regime'] == 'high']
    m_orig = compute_metrics(orig_high)
    
    print(f"{'Metric':<15} | {'Baseline (Lookahead)':>20} | {'Rolling (Real-Time)':>20} | {'Lagged (T-1)':>20}")
    print("-" * 85)
    for k in ["Net Profit", "PF", "Sharpe", "Max DD", "Trades"]:
        v_orig = m_orig[k]
        v_roll = m_roll[k]
        v_lag = m_lag[k]
        
        # Format
        if k == "Trades": fmt = "{:.0f}"
        elif k == "Net Profit" or k == "Max DD": fmt = "${:,.2f}"
        else: fmt = "{:.2f}"
        
        print(f"{k:<15} | {fmt.format(v_orig):>20} | {fmt.format(v_roll):>20} | {fmt.format(v_lag):>20}")

def test_monte_carlo(df):
    print("\n[TEST 2] Monte Carlo Permutation (Edge Authenticity)...")
    
    # 1. Identify High-Vol Subset Baseline
    high_vol_df = df[df['volatility_regime'] == 'high']
    baseline_pf = compute_metrics(high_vol_df)["PF"]
    baseline_net = compute_metrics(high_vol_df)["Net Profit"]
    n_trades = len(high_vol_df)
    
    print(f"Baseline High-Vol: PF {baseline_pf:.2f}, Net ${baseline_net:,.2f}, N={n_trades}")
    
    # 2. Run Simulations
    # Logic: Randomly sample N trades from the *entire population* (all regimes).
    # This tests if "High Vol" trades are statistically superior to "Random" trades.
    # Or does user mean "Shuffle Entry Times within High Vol"?
    # "Within High-vol regime only: Randomly shuffle entry timestamps."
    # AND "Keep exit logic and holding duration unchanged."
    # If I shuffle entry timestamps... and keep holding duration...
    # I effectively just pick a random start time?
    # PnL would change.
    # BUT I can't simulate PnL change without price data.
    # Interpret: He wants me to verify if the *High Volatility Condition* is the driver.
    # If I shuffle *which trades get the High Vol Tag*?
    # That is the permutation test above.
    # If I shuffle the *timestamps* of the High Vol trades, I just reorder the equity curve.
    
    # Decision: I will run the "Random Sampling from Population" test.
    # Why? Because if High Vol is special, then a random sample of N trades from the pool should have lower PF.
    # If High Vol is just "Luck", then random samples will match it.
    
    sim_pfs = []
    sim_nets = []
    
    for _ in range(50):
        # Sample N trades from total df
        # "Randomly shuffle entry timestamps" -> effectively implies random walk through data?
        # User said "Within High-vol regime only: Randomly shuffle entry timestamps."
        # This implies: Take the High Vol Trades. Shuffle their Timestamps *among themselves*?
        # No, that does nothing to PnL.
        
        # Let's assume he means: "Apply the Breakout Logic at Random Times".
        # Since I can't, I will use "Random Sampling of Trades" as best proxy.
        # "Is the High Vol subset distinguishable from random noise?"
        
        sample = df.sample(n=n_trades, replace=False) 
        m = compute_metrics(sample)
        sim_pfs.append(m["PF"])
        sim_nets.append(m["Net Profit"])
        
    avg_pf = np.mean(sim_pfs)
    avg_net = np.mean(sim_nets)
    min_pf = np.min(sim_pfs)
    max_pf = np.max(sim_pfs)
    
    # Count > 1.3
    pass_count = sum(1 for p in sim_pfs if p > 1.3)
    pass_pct = (pass_count / 50) * 100
    
    print(f"Simulations: 50")
    print(f"Avg PF: {avg_pf:.2f} (Range: {min_pf:.2f} - {max_pf:.2f})")
    print(f"Avg Net: ${avg_net:,.2f}")
    print(f"% Sim > 1.3 PF: {pass_pct:.0f}%")
    
    print("\nINTERPRETATION:")
    if baseline_pf > max_pf:
        print("=> Baseline PF is OUTSIDE the simulated distribution. (High Vol is Statistically Significant)")
    elif baseline_pf > avg_pf:
        print("=> Baseline PF is HIGHER than average random sample. (Edge likely exists)")
    else:
        print("=> Baseline PF is indistinguishable from random. (No Edge)")

def main():
    df = load_data()
    if df.empty:
        print("No data.")
        return
        
    test_rolling_vol(df)
    test_monte_carlo(df)

if __name__ == "__main__":
    main()
