import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
SERIES_PREFIX = "Range_Breakout02"

# --- CONFIGURATION ---
# Typical Spreads in Pips (Conservative estimates)
TYPICAL_SPREADS = {
    "AUDNZD": 2.5,
    "AUDUSD": 1.2,
    "EURAUD": 2.0,
    "EURUSD": 1.0,
    "GBPAUD": 2.5,
    "GBPNZD": 3.5,
    "GBPUSD": 1.5,
    "NZDUSD": 1.5,
    "USDCAD": 1.5,
    "USDCHF": 1.5,
    "USDJPY": 1.2
}

# Values specific to OctaFX or Standard 5-digit brokers
PIP_SIZES = {
    "JPY": 0.01,
    "OTHER": 0.0001
}

def get_pip_size(symbol):
    if "JPY" in symbol: return PIP_SIZES["JPY"]
    return PIP_SIZES["OTHER"]

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
                df['entry_price'] = pd.to_numeric(df['entry_price'], errors='coerce')
                df['exit_price'] = pd.to_numeric(df['exit_price'], errors='coerce')
                df['position_units'] = pd.to_numeric(df['position_units'], errors='coerce').fillna(0.0)
                
                df['symbol'] = folder.name.replace(f"{SERIES_PREFIX}_", "")
                all_trades.append(df)
        except Exception:
            pass
            
    if not all_trades: return pd.DataFrame()
    master = pd.concat(all_trades, ignore_index=True)
    master = master.sort_values('entry_timestamp').reset_index(drop=True)
    return master

def compute_metrics(pnl_series):
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

def calculate_friction_cost(row, slippage_pips_roundtrip, added_spread_pips):
    """
    Returns the Cost in USD to SUBTRACT from PnL.
    """
    sym = row['symbol']
    pip_size = get_pip_size(sym)
    
    total_drag_pips = slippage_pips_roundtrip + added_spread_pips
    if total_drag_pips == 0: return 0.0
    
    price_drag = total_drag_pips * pip_size
    price_diff_realized = abs(row['exit_price'] - row['entry_price'])
    
    # Derivation: Cost = (AbsPnL / AbsPriceDiff) * PriceDrag
    if price_diff_realized < pip_size * 0.1:
        # Trade didn't verify move? Use standard fallback.
        # Fallback Calculation:
        # Cost = Units * PriceDrag * (Approx Exchange Rate)
        # Standard Lot = 100,000 units.
        # USD Value per Pip per Lot:
        # USD Quote: $10.
        # USD Base: $10/Price.
        # Cross: $10 * Rate.
        # Hard to do perfectly without rates.
        # Alternative: average 'USD per Pip' from other trades of same symbol?
        # Let's just return 0 if we can't derive. Small price move = Small friction anyway?
        # No, Spread is paid regardless of move size!
        # Critical: We must estimate.
        units = row['position_units']
        # Assume standard $10/lot approx for everything (conservative enough for majors/crosses mix).
        # PipValueUSD ~ 10 * (Units/100000) * DragPips
        cost = 10.0 * (units / 100000.0) * total_drag_pips
        return cost
        
    cost = (abs(row['pnl_usd']) / price_diff_realized) * price_drag
    return cost

def main():
    print("Execution Friction Stress Test (Range_Breakout02 High-Vol)")
    print("=" * 80)
    
    df = load_data()
    if df.empty:
        print("No trades found.")
        return
        
    print(f"Total Trades: {len(df)}")
    
    # BASELINE
    m_base = compute_metrics(df['pnl_usd'])
    
    # SCENARIOS
    # A: Fixed Slippage 0.5 pip/side = 1.0 pip Round Trip. Spread +0.
    # B: Spread Widening +50%. Slippage 0.
    # C: Combined: 1.0 pip Slip + 75% Spread.
    
    results = []
    
    scenarios = [
        ("Baseline", 0.0, 0.0),
        ("A: Fixed Slip (1.0)", 1.0, 0.0),
        ("B: Spread (+50%)", 0.0, 0.5), # "Additional half-spread cost" => 50% widening
        ("C: Severe (1.0 + 75%)", 1.0, 0.75) # 75% widening = 0.75 * Spread
    ]
    
    print("-" * 100)
    print(f"{'Scenario':<25} | {'Net Profit':>12} | {'PF':>6} | {'Sharpe':>6} | {'Max DD':>10} | {'Degradation':>12}")
    print("-" * 100)
    
    # Pre-calculate costs for efficiency
    # But costs depend on Symbol Spread for B/C
    
    for name, slip_pips, spread_mult in scenarios:
        
        adjusted_pnls = []
        
        for idx, row in df.iterrows():
            sym = row['symbol']
            base_spread = TYPICAL_SPREADS.get(sym, 1.5) # Default 1.5 if missing
            
            added_spread_pips = base_spread * spread_mult
            
            cost = calculate_friction_cost(row, slip_pips, added_spread_pips)
            adjusted_pnls.append(row['pnl_usd'] - cost)
            
        series = pd.Series(adjusted_pnls)
        m = compute_metrics(series)
        
        # Comparison
        deg = (1 - (m['Net Profit'] / m_base['Net Profit'])) * 100 if m_base['Net Profit'] != 0 else 0.0
        
        print(f"{name:<25} | ${m['Net Profit']:,.2f} | {m['PF']:6.2f} | {m['Sharpe']:6.2f} | ${m['Max DD']:,.2f} | {deg:11.1f}%")
        
        results.append((name, m))
        
    print("-" * 100)
    
    # Interpretation
    m_b = results[2][1] # Scenario B
    m_c = results[3][1] # Scenario C
    
    verdict = "Fragile"
    if m_b['PF'] > 1.4 and m_c['PF'] > 1.3:
        verdict = "Robust"
    elif m_c['PF'] > 1.2:
        verdict = "Moderately Sensitive"
        
    print(f"VERDICT: {verdict}")
    print(f"  - Scenario B PF: {m_b['PF']:.2f} (>1.4 required for Robust)")
    print(f"  - Scenario C PF: {m_c['PF']:.2f} (>1.3 required for Robust)")

if __name__ == "__main__":
    main()
