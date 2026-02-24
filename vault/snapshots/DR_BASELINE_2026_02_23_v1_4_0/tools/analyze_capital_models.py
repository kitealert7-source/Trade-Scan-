import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
SERIES_PREFIX = "Range_Breakout02"

# --- REFINED MODEL PARAMETERS ---
INITIAL_CAPITAL = 50000.0
RISK_PCT_PER_TRADE = 0.005  # 0.5%
RISK_DOLLAR_PER_TRADE = INITIAL_CAPITAL * RISK_PCT_PER_TRADE # $250
MAX_CONCURRENT_RISK_PCT = 0.02 # 2%
MAX_OPEN_RISK_DOLLARS = INITIAL_CAPITAL * MAX_CONCURRENT_RISK_PCT # $1000

def load_all_high_vol_trades():
    all_trades = []
    for folder in BACKTESTS_ROOT.glob(f"{SERIES_PREFIX}_*"):
        csv_path = folder / "raw" / "results_tradelevel.csv"
        if not csv_path.exists(): continue
        
        try:
            df = pd.read_csv(csv_path)
            # Filter High Vol
            df = df[df['volatility_regime'] == 'high'].copy()
            if not df.empty:
                df['entry_timestamp'] = pd.to_datetime(df['entry_timestamp'])
                df['exit_timestamp'] = pd.to_datetime(df['exit_timestamp'])
                df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0.0)
                df['entry_price'] = pd.to_numeric(df['entry_price'], errors='coerce')
                df['position_units'] = pd.to_numeric(df['position_units'], errors='coerce').fillna(0.0)
                
                # Metrics for Model C sizing
                if 'mae_price' in df.columns:
                    df['mae_price'] = pd.to_numeric(df['mae_price'], errors='coerce').fillna(0.0)
                else:
                    df['mae_price'] = 0.0
                
                # Capture Symbol
                df['symbol'] = folder.name.replace(f"{SERIES_PREFIX}_", "")
                all_trades.append(df)
        except Exception as e:
            print(f"[WARN] Failed to load {folder.name}: {e}")
            
    if not all_trades:
        return pd.DataFrame()
        
    master = pd.concat(all_trades, ignore_index=True)
    master = master.sort_values('entry_timestamp').reset_index(drop=True)
    return master

def compute_refined_model(trades_df):
    """
    Refined Model C:
    - Fixed Dollar Risk ($250)
    - Risk Proxy: Worst Historical MAE (Per Symbol)
    - Max Concurrent Risk Cap ($1000)
    """
    
    # 1. Pre-calculate Risk Proxies (Worst MAE per Symbol)
    # Note: Using absolute MAE price distance.
    # MAE is usually positive distance from Entry.
    # Check if data has negative values? Usually MAE is distance.
    # We'll take max().
    risk_proxies = {}
    for sym, group in trades_df.groupby('symbol'):
        worst_mae = group['mae_price'].max()
        if worst_mae <= 0:
            # Fallback if no MAE recorded or perfect trades (unlikely)
            worst_mae = group['entry_price'].mean() * 0.005 # 0.5% fallback
        risk_proxies[sym] = worst_mae
        
    print("Risk Proxies (Worst Historical MAE):")
    for s, v in risk_proxies.items():
        print(f"  {s:<10}: {v:.5f}")
        
    # 2. Event Loop
    # We need to track open trades to enforce Risk Cap.
    # Events: Entry, Exit.
    # Sort by timestamp.
    # For Entry: Check Cap -> Size -> Record Open.
    # For Exit: Remove Open -> Record PnL.
    
    # Create Event Stream
    events = []
    for idx, row in trades_df.iterrows():
        events.append({
            'time': row['entry_timestamp'],
            'type': 'ENTRY',
            'trade_idx': idx,
            'symbol': row['symbol'],
            'entry_price': row['entry_price'],
            'pnl_raw': row['pnl_usd'],
            'units_raw': row['position_units']
        })
        events.append({
            'time': row['exit_timestamp'],
            'type': 'EXIT',
            'trade_idx': idx
        })
        
    events.sort(key=lambda x: x['time'])
    
    current_equity = INITIAL_CAPITAL
    equity_curve = [(events[0]['time'], INITIAL_CAPITAL)]
    
    open_risk = 0.0
    open_trades = {} # idx -> risk_amount
    
    realized_pnl_total = 0.0
    
    trades_taken = 0
    trades_skipped = 0
    
    peak_concurrent_risk = 0.0
    
    for event in events:
        t_idx = event['trade_idx']
        
        if event['type'] == 'ENTRY':
            # Check Capacity
            if open_risk + RISK_DOLLAR_PER_TRADE > MAX_OPEN_RISK_DOLLARS:
                trades_skipped += 1
                continue
                
            # Sizing
            sym = event['symbol']
            stop_dist = risk_proxies.get(sym, 0.0)
            if stop_dist <= 0: stop_dist = 0.0001
            
            # Units = Risk / Dist
            # Standard FX logic usually implies normalizing for contract size?
            # 'position_units' in raw data is lot_size * contract_size.
            # Here we calculate Raw Units (Contracts).
            new_units = RISK_DOLLAR_PER_TRADE / stop_dist
            
            # Record
            open_risk += RISK_DOLLAR_PER_TRADE
            open_trades[t_idx] = {
                'risk': RISK_DOLLAR_PER_TRADE,
                'units': new_units
            }
            trades_taken += 1
            
            if open_risk > peak_concurrent_risk:
                peak_concurrent_risk = open_risk
                
        elif event['type'] == 'EXIT':
            if t_idx in open_trades:
                trade = open_trades[t_idx]
                
                # release risk
                open_risk -= trade['risk']
                if open_risk < 0: open_risk = 0 # drifting precision
                
                # Calc PnL
                # Scale raw PnL by unit ratio
                raw_row = trades_df.loc[t_idx]
                raw_units = raw_row['position_units']
                raw_pnl = raw_row['pnl_usd']
                
                if raw_units > 0:
                    scale = trade['units'] / raw_units
                    realized_pnl = raw_pnl * scale
                else:
                    realized_pnl = 0.0
                    
                current_equity += realized_pnl
                del open_trades[t_idx]
                
                equity_curve.append((event['time'], current_equity))
                
    # Metrics
    net_profit = current_equity - INITIAL_CAPITAL
    
    # CAGR
    start_dt = events[0]['time']
    end_dt = events[-1]['time']
    years = (end_dt - start_dt).days / 365.25 if end_dt > start_dt else 0
    cagr = (current_equity / INITIAL_CAPITAL) ** (1/years) - 1 if years > 0 else 0
    
    # DD
    eq_vals = [e[1] for e in equity_curve]
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    max_dd_pct = 0.0
    
    for v in eq_vals:
        if v > peak: peak = v
        dd = peak - v
        if dd > max_dd: max_dd = dd
        dd_pct = dd / peak
        if dd_pct > max_dd_pct: max_dd_pct = dd_pct
        
    return {
        "Net Profit": net_profit,
        "CAGR": cagr,
        "Max DD $": max_dd,
        "Max DD %": max_dd_pct * 100,
        "Trades Taken": trades_taken,
        "Trades Skipped": trades_skipped,
        "Peak Risk": peak_concurrent_risk
    }

def main():
    print("Refined Model C Analysis (Fixed Risk, Cap, Worst MAE)")
    print("=" * 80)
    
    df = load_all_high_vol_trades()
    if df.empty:
        print("No trades found.")
        return
        
    print(f"Total Raw Trades: {len(df)}")
    
    res = compute_refined_model(df)
    
    print("-" * 80)
    print(f"Initial Capital:       ${INITIAL_CAPITAL:,.2f}")
    print(f"Risk Per Trade:        ${RISK_DOLLAR_PER_TRADE:,.2f} (0.5% Fixed)")
    print(f"Max Concurrent Risk:   ${MAX_OPEN_RISK_DOLLARS:,.2f} (2.0% Cap)")
    print(f"Risk Proxy:            Worst Historical MAE (Per Symbol)")
    print("-" * 80)
    print(f"Net Profit:            ${res['Net Profit']:,.2f}")
    print(f"Final Equity:          ${(INITIAL_CAPITAL + res['Net Profit']):,.2f}")
    print(f"CAGR:                  {res['CAGR']:.1%}")
    print(f"Max Drawdown:          ${res['Max DD $']:,.2f} ({res['Max DD %']:.2f}%)")
    print(f"Trades Executed:       {res['Trades Taken']} ({res['Trades Taken']/len(df):.1%})")
    print(f"Trades Skipped (Cap):  {res['Trades Skipped']}")
    print(f"Peak Concurrent Risk:  ${res['Peak Risk']:,.2f}")
    print("-" * 80)

if __name__ == "__main__":
    main()
