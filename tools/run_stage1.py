"""
run_stage1.py — Minimal Stage-1 Execution Harness
Purpose: Execute SPX01 directive, emit Stage-1 artifacts only
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

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- CONFIGURATION (from Preflight resolved scope) ---
# --- CONFIGURATION (from Preflight resolved scope) ---
STRATEGY_ID = "VRS004"
SYMBOL = "ETHUSD"
BROKER = "OctaFx"
TIMEFRAME = "4h"
START_DATE = "2020-01-01"
END_DATE = "2025-12-31"
ENGINE_NAME = "Universal_Research_Engine"
ENGINE_VERSION = "1.2.0"
# REFERENCE_CAPITAL removed - derived from broker spec
# PNL_MULTIPLIER removed - derived from broker spec



def load_market_data() -> pd.DataFrame:
    """Load EURUSD Daily data from MASTER_DATA."""
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / "ETH_OCTAFX_MASTER" / "CLEAN"
    
    # Files are split by year. Pattern: ETHUSD_OCTAFX_4h_YYYY_CLEAN.csv
    files = sorted(data_root.glob("ETHUSD_OCTAFX_4h_*_CLEAN.csv"))
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
    """Load VRS002 strategy logic directly."""
    
    class VRS004Strategy:
        def __init__(self):
            self.name = "VRS004 - Momentum and Pullback"
            
        def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
            self.df = df  # Store for price lookup in check_exit
            # RSI(2)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=2).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=2).mean()
            rs = gain / loss
            df['rsi_2'] = 100 - (100 / (1 + rs))
            
            # RSI(2) average of (T-1, T-2)
            df['rsi_2_avg'] = df['rsi_2'].shift(1).rolling(window=2).mean()
            
            # EMA 200
            df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
            
            # EMA slope over last 20 bars
            df['ema_slope_proxy'] = df['ema_200'].diff(20)
            
            # Pre-calculate permissions (Optimization)
            # Uptrend: Price > EMA200 AND Slope > 0
            df['uptrend'] = (df['close'] > df['ema_200']) & (df['ema_slope_proxy'] > 0)
            
            # Downtrend: Price < EMA200 AND Slope < 0
            df['downtrend'] = (df['close'] < df['ema_200']) & (df['ema_slope_proxy'] < 0)
            
            return df

        def check_entry(self, ctx) -> dict:
            row = ctx['row']
            
            # Indicator Values
            rsi_val = row['rsi_2_avg']
            
            # --- LONG LOGIC ---
            # Uptrend Permission
            if row['uptrend']:
                # Entry: RSI(2) avg <= 25
                if rsi_val <= 25:
                    return {
                        "signal": 1,
                        "comment": "RSI_Pullback_Long"
                    }

            # --- SHORT LOGIC ---
            # Downtrend Permission
            if row['downtrend']:
                # Entry: RSI(2) avg >= 75
                if rsi_val >= 75:
                    return {
                        "signal": -1,
                        "comment": "RSI_Pullback_Short"
                    }
            
            return None

        def check_exit(self, ctx) -> dict:
            row = ctx['row']
            # trade info is not in ctx explicitly as 'trade', but we can infer or it might be missing?
            # execution_loop.py says: ctx = "direction": direction...
            # It does NOT pass the 'trade' object itself.
            # But we need 'entry_price' for Stop Loss.
            # execution_loop.py tracks 'entry_price' but doesn't seem to pass it in ctx?
            # Let's check execution_loop.py again.
            
            # Line 29: ctx = { "row": row, "index": i, "direction": direction, "entry_index": entry_index... }
            # It DOES NOT pass entry_price.
            # This is a limitation of the engine 1.2.0?
            
            # Wait, run_execution_loop v1.2.0:
            # entry_price = row['close'] (Line 42)
            # But ctx is built at Line 29.
            # If in_pos, it has entry_index.
            # But entry_price is local variable in loop.
            # Does it put it in ctx? NO.
            
            # Strategy needs entry_price to calculate SL/TP.
            # If engine doesn't pass it, Strategy cannot Calculate SL/TP dynamically?
            # Unless Strategy tracks it? But Strategy is stateless per row?
            
            # Actually, we can get entry_price from df.iloc[entry_index]['close']?
            # But ctx doesn't have df.
            # ctx has 'row'. row has 'close'.
            # ctx has 'entry_index'.
            # We can't access df inside check_exit with this signature?
            
            # Wait, if I can't access entry price, I can't implement "1.5% Stop".
            # Is there a workaround?
            # Maybe the 'trade' IS passed?
            # No.
            
            # Is 'entry_price' available in 'row'? No.
            
            # Maybe I can assume 'context' persists?
            # execution_loop passes 'ctx'.
            
            # If the engine is defective (doesn't pass entry_price), I might be stuck.
            # BUT, look at line 14: "Tracks trade_high ... from entry_bar to exit_bar inclusive."
            # Maybe `ctx` was updated?
            # I read lines 29-35. It sets `ctx` ONCE per iteration.
            
            # However, I can look at strategies/SPX01/example.
            # But I don't have time.
            
            # Wait, `run_execution_loop` at line 7 takes `df`.
            # But `check_exit` only gets `ctx`.
            # If `ctx` does not contain `entry_price` or `df`, I cannot access entry price.
            
            # UNLESS... `check_entry` returns a signal that the engine USES to manage the trade?
            # "Universal_Research_Engine ... Does NOT load data ... Does NOT emit artifacts ... Matches STRATEGY_PLUGIN_CONTRACT.md".
            
            # If I can't implement strict SL/TP, I must abort?
            # Or... is there a field I missed?
            # "entry_index" is in ctx.
            # "bars_held" is in ctx.
            
            # What if I use `ctx['entry_index']`?
            # I can't look up the price at `entry_index` because I don't have `df`.
            
            # WORKAROUND:
            # I can attach `df` to the strategy instance in `prepare_indicators` or `__init__` (if I have access).
            # `prepare_indicators(self, df)` IS called.
            # So I can save `self.df = df`!
            # Then in `check_exit`, I can use `self.df.iloc[ctx['entry_index']]['close']`.
            
            # Clever.
            
            # IMPLEMENTATION:
            # 1. Update prepare_indicators to save self.df = df
            # 2. Update check_exit to look up entry price using ctx['entry_index'].
            
            direction = ctx['direction']
            rsi = row['rsi_2']
            
            # Exhaustion Exit
            if direction == 1 and rsi > 75:
                return {"signal": 1, "comment": "RSI_Exhaustion_Exit"}
            if direction == -1 and rsi < 25:
                return {"signal": 1, "comment": "RSI_Exhaustion_Exit"}

            # FALLBACK: Bars held >= 15
            bars_held = ctx['bars_held']
            if bars_held >= 15:
                return {"signal": 1, "comment": "Time_Exit"}
            
            # Get Entry Price
            entry_idx = ctx['entry_index']
            # Access df stored in self.df
            entry_px = self.df.iloc[entry_idx]['close']
            # Wait, is 'close' reliable? It should be the close of that bar.
            # Yes.
            
            # SL = 1.5%
            # Hard Stop = 2.0%
            
            if direction == 1: # LONG
                sl_price = entry_px * 0.985
                hs_price = entry_px * 0.98
                tp_price = entry_px * 1.03  # 2.0 R (R=1.5% -> 3.0%)
                
                if row['low'] <= hs_price:
                     return {"signal": 1, "comment": "Hard_Stop"}
                if row['low'] <= sl_price:
                     return {"signal": 1, "comment": "Stop_Loss"}
                if row['high'] >= tp_price:
                    return {"signal": 1, "comment": "Take_Profit"}
            
            elif direction == -1: # SHORT
                sl_price = entry_px * 1.015
                hs_price = entry_px * 1.02
                tp_price = entry_px * 0.97 # 2R = 3.0%
                
                if row['high'] >= hs_price:
                    return {"signal": 1, "comment": "Hard_Stop"}
                if row['high'] >= sl_price:
                    return {"signal": 1, "comment": "Stop_Loss"}
                if row['low'] <= tp_price:
                    return {"signal": 1, "comment": "Take_Profit"}

            return None

    strategy_instance = VRS004Strategy()
    print(f"[STRATEGY] Loaded: {strategy_instance.name}")
    return strategy_instance


def run_engine(df, strategy):
    """Run engine execution loop."""
    # Canonical import from versioned directory
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
        
        # Determine position size in lots (assuming engine traded min_lot 0.01 if not specified)
        # In this harness, we assume fixed 0.01 lot for the test unless strategy specified otherwise
        # But strategy objects in current engine don't return size usually?
        # 1.2.0 engine likely returns 'size' in trade dict if implemented.
        # If not, assume min_lot.
        size_lots = t.get('size', min_lot) 
        
        units = size_lots * contract_size
        pnl_usd = (exit_p - entry) * direction * units
        
        # Calculate notional
        # Notional = Units * Entry Price (approx for Forex, accurate for others)
        notional_usd = units * entry
        
        # MFE/MAE
        # Engine 1.2.0 might not emit these. If not, Leave None.
        # Check explicit keys.
        
        if "entry_index" not in t or "exit_index" not in t:
            raise ValueError("Stage-1 requires entry_index and exit_index")

        entry_idx = t["entry_index"]
        exit_idx = t["exit_index"]

        slice_df = df.iloc[entry_idx:exit_idx + 1]

        trade_high = slice_df["high"].max()
        trade_low = slice_df["low"].min()

        # MFE / MAE in price
        if direction == 1:
            mfe_price = trade_high - entry
            mae_price = entry - trade_low
        else:
            mfe_price = entry - trade_low
            mae_price = trade_high - entry

        # Risk per trade = 1.5% (from your strategy SL)
        risk_price = entry * 0.015

        # R metrics
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
    
    # Build metadata
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
    
    # Read directive content
    # Read directive content
    directive_path = PROJECT_ROOT / "backtest_directives" / "active" / "VRS004.md"
    directive_content = directive_path.read_text(encoding="utf-8")
    
    # Output root
    output_root = PROJECT_ROOT / "backtests"
    
    # Emit
    out_folder = emit_stage1(raw_trades, metadata, directive_content, "VRS004.md", output_root)
    print(f"[EMIT] Stage-1 artifacts written to: {out_folder}")
    return out_folder, metadata.run_id


def main():
    print("=" * 60)
    print("STAGE-1 EXECUTION HARNESS")
    print(f"Strategy: {STRATEGY_ID} | Symbol: {SYMBOL} | Timeframe: {TIMEFRAME}")
    print(f"Date Range: {START_DATE} to {END_DATE}")
    print(f"Engine: {ENGINE_NAME} v{ENGINE_VERSION}")
    print("=" * 60)
    
    # Step 1: Load data
    df = load_market_data()
    
    # Step 2: Load broker spec
    broker_spec = load_broker_spec()
    
    # Step 3: Load strategy
    strategy = load_strategy()
    
    # Step 4: Run engine
    trades = run_engine(df, strategy)
    
    if not trades:
        print("[WARN] No trades generated. Exiting.")
        return
    
    # Step 5: Emit Stage-1 artifacts
    out_folder, run_id = emit_stage1_artifacts(trades, df, broker_spec)
    
    # Step 6: Strategy Persistence Enforcement
    save_strategy_snapshot(strategy, run_id, STRATEGY_ID)
    
    print("=" * 60)
    print("Stage-1 execution completed for VRS004 — artifacts written")
    print("=" * 60)

def save_strategy_snapshot(strategy, run_id, strategy_name):
    """Save the strategy class source code to strategies/{run_id}/strategy.py."""
    import inspect
    import os
    import textwrap
    
    target_dir = PROJECT_ROOT / "strategies" / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "strategy.py"
    
    try:
        source = inspect.getsource(strategy.__class__)
        source = textwrap.dedent(source)
        
        # Add required imports
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
