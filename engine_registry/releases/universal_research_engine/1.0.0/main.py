import sys
import os
import yaml
import pandas as pd
import numpy as np
import importlib.util
import uuid
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
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
    EmissionResult
)

def load_broker_spec(broker: str, symbol: str) -> dict:
    """Load broker spec YAML and extract reference_capital_usd."""
    spec_path = PROJECT_ROOT / "data_access" / "broker_specs" / broker / f"{symbol}.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"[GOVERNANCE ERROR] Broker spec not found: {spec_path}")
    with open(spec_path, "r") as f:
        spec = yaml.safe_load(f)
    if "reference_capital_usd" not in spec or spec["reference_capital_usd"] is None:
        raise ValueError(f"[GOVERNANCE ERROR] reference_capital_usd not specified in broker spec: {spec_path}")
    return spec

def load_spx_data():
    """Load SPX500 daily data from MASTER_DATA."""
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / "SPX500_OCTAFX_MASTER" / "CLEAN"
    files = sorted(data_root.glob("SPX500_OCTAFX_1d_*_CLEAN.csv"))
    
    dfs = []
    for f in files:
        df = pd.read_csv(f)
        dfs.append(df)
        
    if not dfs:
        raise FileNotFoundError(f"No SPX500 data found in {data_root}")
        
    combined = pd.concat(dfs, ignore_index=True)
    if 'time' in combined.columns:
        combined['timestamp'] = combined['time']
    
    # Ensure numeric
    cols = ['open', 'high', 'low', 'close']
    for c in cols:
        combined[c] = pd.to_numeric(combined[c], errors='coerce')

    combined = combined.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    return combined

def run_universal_engine(directive_path: str, strategy_name: str):
    print(f"[ENGINE] Running Universal Engine for {strategy_name}")
    
    # 1. Load Logic Module
    if strategy_name == "SPX01":
        from strategies.SPX01 import spx01_logic as logic
        df = load_spx_data()
        symbol = "SPX500"
        timeframe = "D1"
        broker = "OctaFx"
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")
        
    # 2. Indicators
    print("Calculating indicators...")
    df = logic.calculate_indicators(df)
    
    # Load reference_capital_usd from broker spec (Capital Governance)
    broker_spec = load_broker_spec(broker, symbol)
    notional_usd = float(broker_spec["reference_capital_usd"])
    print(f"Using reference_capital_usd = {notional_usd} (from broker spec)")
    
    # 3. Execution Loop
    print("Running backtest loop...")
    trades = []
    in_pos = False
    entry_idx = 0
    entry_price = 0.0
    
    # Start after warm-up (e.g. 20 bars)
    start_idx = 20
    
    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        prev3 = df.iloc[i-3]
        
        if in_pos:
            best_price = max(best_price, row["high"])
            worst_price = min(worst_price, row["low"])
            
            bars_held = i - entry_idx
            should_exit, reason = logic.check_exit(row, bars_held)
            
            if should_exit:
                exit_price = row['close']
                pnl_pct = (exit_price - entry_price) / entry_price
                pnl_usd = pnl_pct * notional_usd
                
                trade_record = TradeRecord(
                    strategy_name=strategy_name,
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
                    position_units=notional_usd/entry_price,
                    notional_usd=notional_usd,
                    mfe_price=best_price - entry_price, 
                    mae_price=worst_price - entry_price, 
                    mfe_r=0.0, 
                    mae_r=0.0
                )
                trades.append(trade_record)
                in_pos = False
                continue
        
        else: # Flat
            if logic.check_entry(row, prev, prev2, prev3):
                entry_price = row['close']
                best_price = entry_price
                worst_price = entry_price
                entry_idx = i
                in_pos = True

    print(f"Generated {len(trades)} trades.")
    if not trades:
        print("No trades generated.")
        return

    # 4. Metrics & Emission
    df_trades = pd.DataFrame([t.__dict__ for t in trades])
    net_pnl = df_trades['net_pnl'].sum()
    trade_count = len(trades)
    win_rate = (df_trades['net_pnl'] > 0).sum() / trade_count if trade_count > 0 else 0
    gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
    gross_loss = abs(df_trades[df_trades['net_pnl'] <= 0]['net_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    
    std_metrics = StandardMetrics(net_pnl_usd=net_pnl, win_rate=win_rate, profit_factor=profit_factor, trade_count=trade_count)
    
    cum_pnl = df_trades['net_pnl'].cumsum()
    max_dd_usd = (cum_pnl.cummax() - cum_pnl).max()
    max_dd_pct = max_dd_usd / notional_usd
    risk_metrics = RiskMetrics(max_drawdown_usd=max_dd_usd, max_drawdown_pct=max_dd_pct, return_dd_ratio=net_pnl/max_dd_usd if max_dd_usd > 0 else 0)
    
    yearwise = []
    df_trades['year'] = pd.to_datetime(df_trades['exit_timestamp']).dt.year
    for yr, grp in df_trades.groupby('year'):
        yearwise.append(YearwiseRecord(
            year=int(yr),
            net_pnl_usd=grp['net_pnl'].sum(),
            trade_count=len(grp),
            win_rate=(grp['net_pnl'] > 0).sum() / len(grp) if len(grp) > 0 else 0
        ))
    
    glossary = [GlossaryEntry("net_pnl_usd", "Net Profit", "Total PnL", "USD")]
    
    with open(directive_path, "r") as f:
        directive_content = f.read()
        
    meta = RunMetadata(
        run_id=str(uuid.uuid4()),
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        date_range_start=str(df['timestamp'].iloc[0]),
        date_range_end=str(df['timestamp'].iloc[-1]),
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name="Universal_Research_Engine",
        engine_version="1.0.0",
        directive_hash="hash",
        engine_hash="hash",
        data_fingerprint="hash",
        schema_version="1.0.0"
    )
    
    # Attach capital & broker context explicitly (governance-surfaced)
    meta.reference_capital_usd = notional_usd
    meta.broker = broker
    meta.position_sizing_basis = "DEFAULT AS PER TRADE_SCAN"
    
    result = emit_results(trades, std_metrics, risk_metrics, yearwise, glossary, meta, directive_content, Path(directive_path).name)
    print(f"Emission Result: {result}")
    
    # Governance Gate — wired to explicit runtime checks
    governance_passed = True
    governance_reason = None
    
    # Check 1: broker spec successfully loaded (already enforced above with exception)
    # Check 2: reference_capital_usd present and numeric
    if not isinstance(notional_usd, (int, float)) or notional_usd <= 0:
        governance_passed = False
        governance_reason = f"reference_capital_usd invalid: {notional_usd}"
    
    # Check 3: all emitted TradeRecords have non-null notional_usd
    if governance_passed:
        for i, t in enumerate(trades):
            if t.notional_usd is None or t.notional_usd <= 0:
                governance_passed = False
                governance_reason = f"Trade {i} has invalid notional_usd: {t.notional_usd}"
                break
    
    # Check 4: emit_results() returned SUCCESS
    if governance_passed and result != EmissionResult.SUCCESS:
        governance_passed = False
        governance_reason = f"Emission failed: {result}"
    
    if result == EmissionResult.SUCCESS:
        if governance_passed:
            import subprocess
            run_folder = PROJECT_ROOT / "backtests" / strategy_name
            print("Running Stage-2...")
            subprocess.run(["python", str(PROJECT_ROOT / "tools/stage2_compiler.py"), str(run_folder)])
            print("Running Stage-3...")
            subprocess.run(["python", str(PROJECT_ROOT / "tools/stage3_compiler.py")])
        else:
            print(f"[GOVERNANCE] Stage-2/3 skipped: {governance_reason}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python main.py <directive_path> <strategy_name>")
        sys.exit(1)
    run_universal_engine(sys.argv[1], sys.argv[2])
