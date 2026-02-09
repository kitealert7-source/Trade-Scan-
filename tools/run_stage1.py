"""
run_stage1.py — Minimal Stage-1 Execution Harness
Purpose: Execute SPX04 directive, emit Stage-1 artifacts only
Authority: SOP_TESTING, SOP_OUTPUT

NO METRICS COMPUTATION
NO STAGE-2 OR STAGE-3
"""

import sys
import uuid
from pathlib import Path
from datetime import datetime
import yaml
import pandas as pd
import numpy as np

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- CONFIGURATION ---
STRATEGY_ID = "SPX04"
SYMBOL = "SPX500"
BROKER = "OctaFx"
TIMEFRAME = "1d"
START_DATE = "2015-01-01"
END_DATE = "2026-01-31"
ENGINE_NAME = "Universal_Research_Engine"
ENGINE_VERSION = "1.2.0"


def load_market_data() -> pd.DataFrame:
    """Load SPX500 Daily data from MASTER_DATA."""
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / "SPX500_OCTAFX_MASTER" / "CLEAN"
    
    # Files are split by year. Pattern: SPX500_OCTAFX_1d_YYYY_CLEAN.csv
    files = sorted(data_root.glob("SPX500_OCTAFX_1d_*_CLEAN.csv"))
    if not files:
        raise FileNotFoundError(f"No daily data files found in {data_root}")
    
    dfs = [pd.read_csv(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    # Normalize timestamp column
    if 'time' in df.columns:
        df['timestamp'] = df['time']
    
    # Deduplicate and sort
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    
    # Filter by date range
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    df = df.reset_index(drop=True)
    
    print(f"[DATA] Loaded {len(df)} bars from {data_root}")
    return df


def load_broker_spec() -> dict:
    """Load broker specification for symbol."""
    broker_spec_path = PROJECT_ROOT / "data_access" / "broker_specs" / BROKER / f"{SYMBOL}.yaml"
    if not broker_spec_path.exists():
        raise FileNotFoundError(f"Broker spec not found: {broker_spec_path}")
    
    with open(broker_spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
        
    required = ["contract_size", "min_lot"]
    for field in required:
        if field not in spec or spec[field] is None:
            raise ValueError(f"Broker spec missing mandatory field: {field}")
            
    print(f"[BROKER] Loaded spec for {SYMBOL} (Contract Size: {spec['contract_size']})")
    return spec


def load_strategy():
    """Load SPX04 strategy logic directly."""
    
    class SPX04Strategy:
        def __init__(self):
            self.name = "SPX04 - Dip Buying (4-bar Exit)"
            self.df = None
            
        def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
            # HH (5 bars)
            # "Highest High of previous 5 completed bars"
            df['hh_5_prev'] = df['high'].rolling(window=5).max().shift(1)
            
            # ATR (10)
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df['atr_10'] = tr.rolling(window=10).mean()
            
            # "Previous 5 completed bars - ATR(10)"?
            # Implies ATR(10 of PREVIOUS 5 bars?) or ATR(10) at t-1?
            # Same interpretation as SPX02.
            df['atr_10_prev'] = df['atr_10'].shift(1)
            
            # Entry Threshold
            df['entry_threshold'] = df['hh_5_prev'] - df['atr_10_prev']
            
            # Store DF
            self.df = df
            return df

        def check_entry(self, ctx) -> dict:
            row = ctx['row']
            
            # Logic: Close < (HH_prev - ATR_prev)
            
            close = row['close']
            threshold = row['entry_threshold']
            
            if pd.isna(threshold):
                return None
            
            if close < threshold:
                return {
                    "signal": 1,
                    "comment": "Dip_Buy"
                }
            
            return None

        def check_exit(self, ctx) -> dict:
            row = ctx['row']
            
            # 1. Price Exit: Close > HH_prev
            close = row['close']
            hh_prev = row['hh_5_prev']
            
            if not pd.isna(hh_prev) and close > hh_prev:
                return {
                    "signal": 1,
                    "comment": "Price_Exit_HH"
                }

            # 2. Time Exit: Bars Held >= 4 (SPX04)
            if ctx['bars_held'] >= 4:
                return {
                    "signal": 1,
                    "comment": "Time_Exit_4"
                }

            return None

    strategy_instance = SPX04Strategy()
    print(f"[STRATEGY] Loaded: {strategy_instance.name}")
    return strategy_instance


def run_engine(df, strategy):
    """Run engine execution loop."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "execution_loop",
        PROJECT_ROOT / "engine_dev/universal_research_engine/1.2.0/execution_loop.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_execution_loop = module.run_execution_loop

    trades = run_execution_loop(df, strategy)
    print(f"[ENGINE] Generated {len(trades)} trades")
    return trades


def emit_stage1_artifacts(trades, df, broker_spec):
    """Emit Stage-1 artifacts only."""
    from tools.execution_emitter_stage1 import emit_stage1, RawTradeRecord, Stage1Metadata
    
    contract_size = float(broker_spec["contract_size"])
    min_lot = float(broker_spec["min_lot"])
    
    raw_trades = []
    for i, t in enumerate(trades):
        entry = t['entry_price']
        exit_p = t['exit_price']
        direction = t['direction'] if t['direction'] != 0 else 1
        
        size_lots = t.get('size', min_lot) 
        
        units = size_lots * contract_size
        pnl_usd = (exit_p - entry) * direction * units
        
        notional_usd = units * entry
        
        if "entry_index" not in t or "exit_index" not in t:
            raise ValueError("Stage-1 requires entry_index and exit_index")

        entry_idx = t["entry_index"]
        exit_idx = t["exit_index"]

        slice_df = df.iloc[entry_idx:exit_idx + 1]

        trade_high = slice_df["high"].max()
        trade_low = slice_df["low"].min()

        if direction == 1:
            mfe_price = trade_high - entry
            mae_price = entry - trade_low
        else:
            mfe_price = entry - trade_low
            mae_price = trade_high - entry

        risk_price = 0.0
        
        r_multiple = pnl_usd / (risk_price * units) if risk_price > 0 else 0.0
        mfe_r = mfe_price / risk_price if risk_price > 0 else 0.0
        mae_r = mae_price / risk_price if risk_price > 0 else 0.0

        raw_trades.append(RawTradeRecord(
            strategy_name=STRATEGY_ID,
            parent_trade_id=i + 1,
            sequence_index=i,
            entry_timestamp=str(t['entry_timestamp']),
            exit_timestamp=str(t['exit_timestamp']),
            direction=direction,
            entry_price=entry,
            exit_price=exit_p,
            bars_held=t['bars_held'],
            pnl_usd=round(pnl_usd, 2),
            trade_high=trade_high,
            trade_low=trade_low,
            atr_entry=t.get('atr'),
            position_units=units,
            notional_usd=round(notional_usd, 2),
            mfe_price=round(mfe_price, 4),
            mae_price=round(mae_price, 4),
            mfe_r=round(mfe_r, 2),
            mae_r=round(mae_r, 2),
            r_multiple=round(r_multiple, 2)
        ))
    
    metadata = Stage1Metadata(
        run_id=str(uuid.uuid4()),
        strategy_name=STRATEGY_ID,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        date_range_start=START_DATE,
        date_range_end=END_DATE,
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        broker=BROKER,
        reference_capital_usd=float(broker_spec["reference_capital_usd"])
    )
    
    directive_path = PROJECT_ROOT / "backtest_directives" / "active" / "SPX04.txt"
    directive_content = directive_path.read_text(encoding="utf-8")
    
    output_root = PROJECT_ROOT / "backtests"
    
    out_folder = emit_stage1(raw_trades, metadata, directive_content, "SPX04.txt", output_root)
    print(f"[EMIT] Stage-1 artifacts written to: {out_folder}")
    return out_folder, metadata.run_id


def main():
    print("=" * 60)
    print("STAGE-1 EXECUTION HARNESS")
    print(f"Strategy: {STRATEGY_ID} | Symbol: {SYMBOL} | Timeframe: {TIMEFRAME}")
    print(f"Date Range: {START_DATE} to {END_DATE}")
    print(f"Engine: {ENGINE_NAME} v{ENGINE_VERSION}")
    print("=" * 60)
    
    df = load_market_data()
    broker_spec = load_broker_spec()
    strategy = load_strategy()
    trades = run_engine(df, strategy)
    
    if not trades:
        print("[WARN] No trades generated. Exiting.")
        return
    
    if trades:
        out_folder, run_id = emit_stage1_artifacts(trades, df, broker_spec)
        save_strategy_snapshot(strategy, run_id, STRATEGY_ID)
        
        print("=" * 60)
        print("Stage-1 execution completed for SPX04 — artifacts written")
        print("=" * 60)
    else:
        print("No trades to emit.")


def save_strategy_snapshot(strategy, run_id, strategy_name):
    import inspect
    import os
    import textwrap
    
    target_dir = PROJECT_ROOT / "strategies" / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "strategy.py"
    
    try:
        source = inspect.getsource(strategy.__class__)
        source = textwrap.dedent(source)
        
        content = (
            "\"\"\"\n"
            f"Strategy: {strategy_name}\n"
            f"Run ID: {run_id}\n"
            "Auto-generated by Trade_Scan persistence mechanism.\n"
            "\"\"\"\n"
            "import pandas as pd\n"
            "import numpy as np\n\n"
            f"{source}"
        )
        
        target_file.write_text(content, encoding="utf-8")
        print(f"[PERSISTENCE] Strategy logic saved to: {target_file}")
        
    except Exception as e:
        print(f"[WARN] Failed to save strategy snapshot: {e}")


if __name__ == "__main__":
    main()
