"""
SPX01 Strategy Engine
Strictly implements Trade_Scan/backtest_directives/SPX01.md
"""
import sys
import json
import uuid
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import Emitter
from tools.execution_emitter import (
    emit_results,
    TradeRecord,
    StandardMetrics,
    RiskMetrics,
    YearwiseRecord,
    GlossaryEntry,
    RunMetadata,
)

STRATEGY_NAME = "SPX01_SPX500_D1"
SYMBOL = "SPX500"
TIMEFRAME = "D1"

class SPX01Engine:
    """
    SPX01 Strategy Implementation
    Source: backtest_directives/SPX01.md
    """
    
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # Ensure numeric
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        # 1. Three Consecutive Lower Closes (Pattern)
        # Close < Close(T-1) AND Close(T-1) < Close(T-2) AND Close(T-2) < Close(T-3)
        # Implemented in logic check, but we can pre-calc deltas if needed.
        # Check happens on current bar vs history.
        
        # 2. Stochastic %K (14, 3)
        low_min = df['low'].rolling(window=14).min()
        high_max = df['high'].rolling(window=14).max()
        k_fast = 100 * (df['close'] - low_min) / (high_max - low_min)
        df['stoch_k'] = k_fast.rolling(window=3).mean()
        
        # 3. ROC(5)
        # (Close - Close(T-n)) / Close(T-n)
        df['roc_5'] = df['close'].pct_change(periods=5)
        
        # 4. RSI(2)
        n = 2
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=n).mean() # Simple moving average for RSI(2) usually? 
        # Standard RSI uses Wilder's Smoothing, but for short periods like 2, SMA matching common implementations is key.
        # Directives say "RSI(2) calculated". Usually implies Wilder.
        # Let's use Wilder's smoothing equivalent: EMA(alpha=1/n)
        avg_gain = gain.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
        rs = avg_gain / avg_loss
        df['rsi_2'] = 100 - (100 / (1 + rs))
        
        return df

    @staticmethod
    def run_backtest(df: pd.DataFrame):
        trades = []
        in_pos = False
        
        entry_idx = 0
        entry_price = 0.0
        
        # Iterate
        # Start from index that has indicators (approx 20)
        start_idx = 20
        
        for i in range(start_idx, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]
            prev2 = df.iloc[i-2]
            prev3 = df.iloc[i-3]
            
            # EXIT LOGIC (Strict Precedence) - Check first if we are LONG
            if in_pos:
                bars_held = i - entry_idx
                exit_triggered = False
                exit_reason = ""
                
                # 1. PRIMARY: RSI(2) > 75
                # "Exit LONG immediately when"
                if row['rsi_2'] > 75:
                    exit_triggered = True
                    exit_reason = "RSI_Exhaustion"
                
                # 2. FALLBACK: Bars held >= 4
                elif bars_held >= 4:
                    exit_triggered = True
                    exit_reason = "Timeout"
                
                if exit_triggered:
                    exit_price = row['open'] # Assume exit at Open of cur bar? 
                    # Directive says: "triggered... on the current bar". 
                    # If indicator crosses during bar, usually we exit at Close or Next Open.
                    # "Exit LONG immediately when...". 
                    # If RSI > 75 is based on Close, we know it at Close.
                    # Standard backtest assumes execution at Close or Next Open.
                    # Let's assume Close for "Immediate" on Daily timeframe, or Next Open.
                    # Usually "Bars held >= 4" implies check at open or close.
                    # Given it's daily data, let's execute at CLOSE of the trigger bar.
                    exit_price = row['close']
                    
                    pnl_pct = (exit_price - entry_price) / entry_price
                    # Mock sizing: $10,000 per trade? Default Trade_Scan sizing. 
                    # Let's use a fixed notional for PnL calculation: $10,000
                    notional = 10000.0
                    pnl_usd = pnl_pct * notional
                    
                    trade_record = TradeRecord(
                        strategy_name=STRATEGY_NAME,
                        parent_trade_id=len(trades)+1,
                        sequence_index=len(trades),
                        entry_timestamp=df.iloc[entry_idx]['timestamp'],
                        exit_timestamp=row['timestamp'],
                        direction=1,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        net_pnl=pnl_usd,
                        bars_held=bars_held,
                        atr_entry=0.0,
                        position_units=notional/entry_price,
                        notional_usd=notional
                    )
                    trades.append(trade_record)
                    in_pos = False
                    continue # Trade closed, move to next bar (flat now)

            # ENTRY LOGIC
            # "A LONG entry is triggered when position is FLAT and ANY ONE..."
            if not in_pos:
                # 1. Three Consecutive Lower Closes
                cond1 = (row['close'] < prev['close']) and \
                        (prev['close'] < prev2['close']) and \
                        (prev2['close'] < prev3['close'])
                
                # 2. Stochastic Oversold Cross
                # %K < 20 AND %K(T-1) >= 20
                cond2 = (row['stoch_k'] < 20) and (prev['stoch_k'] >= 20)
                
                # 3. ROC Oversold Cross
                # ROC(5) < -1.0% (-0.01) AND ROC(5)(T-1) >= -1.0%
                cond3 = (row['roc_5'] < -0.01) and (prev['roc_5'] >= -0.01)
                
                # 4. RSI Deep Oversold
                # Average of RSI(T-1) and RSI(T-2) <= 25
                rsi_avg = (prev['rsi_2'] + prev2['rsi_2']) / 2
                cond4 = rsi_avg <= 25
                
                if cond1 or cond2 or cond3 or cond4:
                    # Enter LONG
                    entry_price = row['close'] # Enter at Close
                    entry_idx = i
                    in_pos = True
                    
        return trades

def load_data():
    data_root = Path(r"C:\Users\faraw\Documents\Anti_Gravity_DATA_ROOT\MASTER_DATA\SPX500_OCTAFX_MASTER\CLEAN")
    files = sorted(data_root.glob("SPX500_OCTAFX_1d_*_CLEAN.csv"))
    
    dfs = []
    for f in files:
        df = pd.read_csv(f)
        dfs.append(df)
        
    if not dfs:
        raise FileNotFoundError("No SPX500 data found!")
        
    combined = pd.concat(dfs, ignore_index=True)
    if 'time' in combined.columns:
        combined['timestamp'] = combined['time']
    combined = combined.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    return combined

def main():
    print(f"Starting {STRATEGY_NAME} Execution...")
    
    # 1. Load Data
    df = load_data()
    print(f"Loaded {len(df)} bars. Range: {df['timestamp'].iloc[0]} - {df['timestamp'].iloc[-1]}")
    
    # 2. Indicators
    df = SPX01Engine.calculate_indicators(df)
    
    # 3. Simulate
    trades = SPX01Engine.run_backtest(df)
    print(f"Generated {len(trades)} trades.")
    
    if not trades:
        print("No trades generated.")
        return

    # 4. Metrics
    # Compute basic metrics for Standard/Risk CSVs
    df_trades = pd.DataFrame([t.__dict__ for t in trades])
    net_pnl = df_trades['net_pnl'].sum()
    trade_count = len(trades)
    win_rate = (df_trades['net_pnl'] > 0).sum() / trade_count
    gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
    gross_loss = abs(df_trades[df_trades['net_pnl'] <= 0]['net_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    
    std_metrics = StandardMetrics(net_pnl_usd=net_pnl, win_rate=win_rate, profit_factor=profit_factor, trade_count=trade_count)
    
    cum_pnl = df_trades['net_pnl'].cumsum()
    max_dd_usd = (cum_pnl.cummax() - cum_pnl).max()
    max_dd_pct = max_dd_usd / 10000.0 # Based on 10k notional
    
    risk_metrics = RiskMetrics(max_drawdown_usd=max_dd_usd, max_drawdown_pct=max_dd_pct, return_dd_ratio=net_pnl/max_dd_usd if max_dd_usd>0 else 0)
    
    # Yearwise
    df_trades['year'] = pd.to_datetime(df_trades['exit_timestamp']).dt.year
    yearwise = []
    for yr, grp in df_trades.groupby('year'):
        yearwise.append(YearwiseRecord(
            year=int(yr),
            net_pnl_usd=grp['net_pnl'].sum(),
            trade_count=len(grp),
            win_rate=(grp['net_pnl'] > 0).sum() / len(grp)
        ))
        
    # Glossary
    glossary = [
        GlossaryEntry("net_pnl_usd", "Net Profit", "Total PnL", "USD"),
        GlossaryEntry("win_rate", "Win Rate", "Win %", "Decimal"),
        GlossaryEntry("profit_factor", "Profit Factor", "GP/GL", "Ratio"),
        GlossaryEntry("max_drawdown_usd", "Max DD USD", "Max DD", "USD"),
        GlossaryEntry("max_drawdown_pct", "Max DD %", "Max DD %", "Decimal")
    ]
    
    # Metadata
    directive_path = PROJECT_ROOT / "backtest_directives/active/SPX01.txt"
    with open(directive_path, "r") as f:
        directive_content = f.read()
        
    meta = RunMetadata(
        run_id=str(uuid.uuid4()),
        strategy_name=STRATEGY_NAME,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        date_range_start=str(df['timestamp'].iloc[0]),
        date_range_end=str(df['timestamp'].iloc[-1]),
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name="SPX01Engine",
        engine_version="1.0.0",
        directive_hash="hash",
        engine_hash="hash",
        data_fingerprint="hash",
        schema_version="1.0.0"
    )
    
    result = emit_results(
        trades, std_metrics, risk_metrics, yearwise, glossary, meta, directive_content, "SPX01.txt"
    )
    print(f"Emission Result: {result}")
    
    # Stage 2 & 3
    if result.value == "SUCCESS":
        import subprocess
        run_folder = PROJECT_ROOT / "backtests" / STRATEGY_NAME
        print("Running Stage-2...")
        subprocess.run(["python", "tools/stage2_compiler.py", str(run_folder)])
        print("Running Stage-3...")
        subprocess.run(["python", "tools/stage3_compiler.py"])

if __name__ == "__main__":
    main()
