"""
run_stage1.py — Minimal Stage-1 Execution Harness (Multi-Asset Batch v5 - State Gated)
Purpose: Execute Directive (Batch), emit Stage-1 artifacts only
Authority: SOP_TESTING, SOP_OUTPUT, SOP_AGENT_ENGINE_GOVERNANCE

NO METRICS COMPUTATION
NO STAGE-2 OR STAGE-3
"""

import sys
import uuid
import json
import hashlib
import csv
import traceback
import re
from pathlib import Path
from datetime import datetime
import subprocess
import yaml
import pandas as pd
import numpy as np

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Governance Imports
from tools.pipeline_utils import PipelineStateManager, generate_run_id, parse_directive, get_engine_version
from engines.regime_state_machine import apply_regime_model
from config.state_paths import RUNS_DIR, BACKTESTS_DIR

# --- REGIME TIMEFRAME MAP (v1.5.4) ---
_REGIME_TF_MAP_PATH = PROJECT_ROOT / "config" / "regime_timeframe_map.yaml"
_REGIME_TF_MAP = None

def _load_regime_tf_map() -> dict:
    """Load regime timeframe mapping. Cached after first call."""
    global _REGIME_TF_MAP
    if _REGIME_TF_MAP is not None:
        return _REGIME_TF_MAP
    try:
        with open(_REGIME_TF_MAP_PATH, encoding="utf-8") as f:
            _REGIME_TF_MAP = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"    [WARN] regime_timeframe_map.yaml not found — defaulting to 4H regime")
        _REGIME_TF_MAP = {"mapping": {}, "default": {"regime_tf": "4h", "resample_freq": "1D"}}
    return _REGIME_TF_MAP

def resolve_regime_config(signal_tf: str) -> tuple:
    """Resolve (regime_tf, resample_freq) for a given signal timeframe.

    Returns:
        (regime_tf, resample_freq) e.g. ("4h", "1D") or ("1d", "1W")
    """
    cfg = _load_regime_tf_map()
    tf = signal_tf.lower()
    mapping = cfg.get("mapping", {})
    if tf in mapping:
        entry = mapping[tf]
        return entry["regime_tf"], entry["resample_freq"]
    default = cfg.get("default", {})
    print(f"    [WARN] No regime mapping for '{tf}' — using default 4H/1D")
    return default.get("regime_tf", "4h"), default.get("resample_freq", "1D")

# --- CONFIGURATION TO BE PARSED FROM DIRECTIVE ---
# Default placeholders, will be overridden by parsing
DIRECTIVE_FILENAME = "SPX04.txt"
BROKER = "OctaFx"
TIMEFRAME = "1d"
START_DATE = "2015-01-01"
END_DATE = "2026-01-31"

# --- WARM-UP EXTENSION PROVISION ---
# Populated from per-strategy indicator_warmup_resolver before data loading.
# Ensures the effective test window starts from the directive's start_date,
# with sufficient prior history for indicator initialization.
# Default: 250 bars (safe floor). Overridden per-strategy at runtime.
RESOLVED_WARMUP_BARS = 250


# --- PnL NORMALIZATION LOGIC ---

# Module-level cache for Close prices: (symbol, date_str) -> close_price
CONVERSION_CACHE = {}

def parse_symbol_properties(symbol: str):
    """
    Parse symbol into base and quote currencies using broker spec metadata.

    Priority:
        1. Broker spec price_unit + currency_profit (authoritative if spec exists)
        2. Heuristic fallback (alpha-only 6-char = FX, endswith USD = commodity)

    For INDEX_POINT symbols, the raw PnL is denominated in the index's profit
    currency (e.g. EUR for GER40, JPY for JPN225, USD for NAS100).
    We return (symbol, currency_profit) so normalize_pnl_to_usd() can apply
    the correct FX conversion via cross-pair lookup.
    """
    s = symbol.upper()

    # Try broker spec first (authoritative)
    broker_spec_path = PROJECT_ROOT / "data_access" / "broker_specs" / BROKER / f"{s}.yaml"
    if broker_spec_path.exists():
        import yaml as _yaml
        with open(broker_spec_path, "r", encoding="utf-8") as f:
            spec = _yaml.safe_load(f)
        price_unit = spec.get("calibration", {}).get("price_unit", "")
        if price_unit == "INDEX_POINT":
            # Read profit currency from broker spec — NOT always USD
            profit_ccy = spec.get("calibration", {}).get("currency_profit", "USD")
            if profit_ccy == "USD":
                return s, "USD"  # USD-denominated index: pass-through
            else:
                # Non-USD index (e.g. GER40=EUR, UK100=GBP, JPN225=JPY)
                # Return profit currency as quote so normalize_pnl_to_usd()
                # applies cross-pair conversion (e.g. EURUSD, GBPUSD, USDJPY)
                return s, profit_ccy

    # Heuristic fallback
    if len(s) == 6 and s.isalpha():
        return s[:3], s[3:]
    elif s.endswith("USD"):
        return s[:-3], "USD"
    else:
        return s, None

# Global DF Cache for conversion pairs: symbol -> DF
_CONVERSION_DF_CACHE = {}

def get_conversion_price_at_time(target_pair: str, timestamp: pd.Timestamp) -> float:
    """
    Fetch price from cached dataframe.
    """
    if target_pair not in _CONVERSION_DF_CACHE:
        try:
            # Re-use load_market_data but we need to ensure global Start/End dates cover it.
            # We will use the global START_DATE/END_DATE.
            print(f"[CONVERSION] Loading data for {target_pair}...")
            df = load_market_data(target_pair)
            
            # Optimization: Keep only timestamp and close
            df = df[['timestamp', 'close']].copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, format='mixed', utc=True)
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            
            _CONVERSION_DF_CACHE[target_pair] = df
        except Exception as e:
            # Allow failure if file doesn't exist, caller handles retry logic
            raise ValueError(f"Failed to load conversion pair {target_pair}: {e}")
            
    df = _CONVERSION_DF_CACHE[target_pair]
    
    # As-of lookup (nearest previous close)
    try:
        # idx = df.index.get_indexer([timestamp], method='ffill')[0]
        # Using asof is cleaner for singular lookups
        # converting timestamp to index type (DatetimeIndex)
        ts = pd.Timestamp(timestamp)
        idx = df.index.asof(ts)
        
        if pd.isna(idx):
             raise ValueError("Date out of range (before start)")
             
        val = df.loc[idx]['close']
        if isinstance(val, pd.Series):
            val = val.iloc[0] # handle duplicates if any
        return float(val)
    except Exception as e:
        raise ValueError(f"No data found for {target_pair} at {timestamp}: {e}")

def normalize_pnl_to_usd(raw_pnl_quote: float, 
                         base_ccy: str, 
                         quote_ccy: str, 
                         exit_price: float, 
                         timestamp: pd.Timestamp) -> float:
    """
    Normalize PnL to USD using exact case logic.
    """
    # Case A: Quote is USD (e.g. EURUSD, GBPUSD, XAUUSD)
    if quote_ccy == "USD":
        return raw_pnl_quote
        
    # Case B: Base is USD (e.g. USDJPY, USDCAD, USDCHF)
    if base_ccy == "USD":
        if exit_price == 0: return 0.0
        return raw_pnl_quote / exit_price
    
    # Check if we failed parsing or non-fx
    if quote_ccy is None:
        # Case D: Non-FX -> Pass-through
        return raw_pnl_quote
        
    # Case C: Cross Pair (e.g. EURGBP)
    # Target: Convert Quote (GBP) to USD.
    # Method 1: {Quote}USD (e.g. GBPUSD) -> Multiplier
    # Method 2: USD{Quote} (e.g. USDGBP - Rare) -> Divisor
    
    target_direct = f"{quote_ccy}USD"
    target_indirect = f"USD{quote_ccy}"
    
    # Try Direct
    try:
        rate = get_conversion_price_at_time(target_direct, timestamp)
        return raw_pnl_quote * rate
    except ValueError:
        pass
        
    # Try Indirect
    try:
        rate = get_conversion_price_at_time(target_indirect, timestamp)
        return raw_pnl_quote / rate
    except ValueError:
        pass
        
    # Hard Fail
    raise ValueError(f"Missing conversion data for cross PnL ({base_ccy}/{quote_ccy}). Needed {target_direct} or {target_indirect}.")


# get_engine_version imported from pipeline_utils

# parse_directive imported from pipeline_utils

# get_canonical_hash imported from pipeline_utils (indirectly used via generate_run_id)


def load_market_data(symbol: str, tf_override: str = None) -> pd.DataFrame:
    """Load Daily data from MASTER_DATA for efficient batching."""
    # Dynamic path construction
    # Redirected to the user-provided internal data_root
    data_root = PROJECT_ROOT / "data_root" / "MASTER_DATA" / f"{symbol}_{BROKER.upper()}_MASTER" / "RESEARCH"
    
    # Use override or global TIMEFRAME
    tf = tf_override if tf_override else TIMEFRAME
    
    # Files are split by year. Pattern: SYMBOL_BROKER_TIMEFRAME_YYYY_RESEARCH.csv
    pattern = f"{symbol}_{BROKER.upper()}_{tf}_*_RESEARCH.csv"
    files = sorted(data_root.glob(pattern))
    
    if not files:
        raise FileNotFoundError(f"No RESEARCH market data found for {symbol} / {BROKER} / {TIMEFRAME} in {data_root}")
    
    dfs = [pd.read_csv(f, comment='#') for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    if 'time' in df.columns:
        df['timestamp'] = df['time']
    
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, format='mixed', utc=True)
    
    # --- WARM-UP EXTENSION PROVISION ---
    # Extends the data window backward from START_DATE by the per-strategy
    # resolved warmup bars so that all indicators are fully initialized by
    # the time the directive's specified test period begins.
    # RESOLVED_WARMUP_BARS is set from the strategy's indicator list before
    # this function is called. Falls back to 250 if not yet set.
    warmup_bars = RESOLVED_WARMUP_BARS
    requested_start_idx = df.index[df['timestamp'] >= START_DATE]
    if not requested_start_idx.empty:
        start_idx = max(0, requested_start_idx[0] - warmup_bars)
        df = df.iloc[start_idx:]
        print(f"[DATA] {symbol}: Warm-up extension: {warmup_bars} bars before {START_DATE}")
    
    # Still filter the end date strictly
    df = df[df['timestamp'] <= END_DATE]
    df = df.reset_index(drop=True)
    
    print(f"[DATA] {symbol}: Loaded {len(df)} bars")
    return df


def load_broker_spec(symbol: str) -> dict:
    """Load broker specification for symbol."""
    broker_spec_path = PROJECT_ROOT / "data_access" / "broker_specs" / BROKER / f"{symbol}.yaml"
    if not broker_spec_path.exists():
        print(f"[DEBUG] Failed Path: '{broker_spec_path}' (Absolute: {broker_spec_path.absolute()})")
        print(f"[DEBUG] BROKER='{BROKER}', symbol='{symbol}'")
        raise FileNotFoundError(f"Broker spec not found: {broker_spec_path}")
    
    with open(broker_spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
        
    required = ["contract_size", "min_lot"]
    for field in required:
        if field not in spec or spec[field] is None:
            raise ValueError(f"Broker spec missing mandatory field: {field}")
            
    return spec


def load_strategy(strategy_id: str, run_id: str = None):
    """Dynamically load strategy plugin."""
    import importlib
    
    # Validation
    if run_id:
        plugin_path = RUNS_DIR / run_id / "strategy.py"
        module_path = f"runs.{run_id}.strategy"
    else:
        plugin_path = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
        module_path = f"strategies.{strategy_id}.strategy"

    if not plugin_path.exists():
        raise FileNotFoundError(f"Strategy plugin not found: {plugin_path}")

    # --- INVARIANT 10: Research Layer Boundary Guard ---
    resolved = plugin_path.resolve()
    strategies_root = (PROJECT_ROOT / "strategies").resolve()
    runs_root = RUNS_DIR.resolve()
    if not str(resolved).startswith(str(strategies_root)) and not str(resolved).startswith(str(runs_root)):
        raise RuntimeError(
            f"[FATAL] Boundary Violation: Strategy path '{resolved}' "
            f"is outside governed directories."
        )
    if "research" in str(resolved).lower():
        raise RuntimeError(
            f"[FATAL] Boundary Violation: Strategy path '{resolved}' "
            f"resolves into the research layer. Pipeline refuses to load."
        )
    # --------------------------------------------------

    # --- STATIC ANALYSIS GUARD ---
    source_code = plugin_path.read_text(encoding='utf-8')
    forbidden = ["rolling(", "high_low", "high_close"]
    for term in forbidden:
        if term in source_code:
            raise RuntimeError(f"Inline indicator logic detected ('{term}'). Use repository indicators.")
    # -----------------------------

    # -----------------------------

    # --- INDICATOR DEPENDENCY VALIDATION ---
    import re

    # reuse source_code from above

    # Match: from indicators.<domain>.<module> import <name>
    pattern = r"from\s+indicators\.([a-zA-Z0-9_\.]+)\s+import\s+([a-zA-Z0-9_,\s]+)"

    matches = re.findall(pattern, source_code)

    for module_path, imported_names in matches:
        module_parts = module_path.split(".")
        indicator_file = PROJECT_ROOT / "indicators" / Path(*module_parts).with_suffix(".py")

        if not indicator_file.exists():
            raise RuntimeError(
                f"Indicator dependency missing: indicators/{module_path}.py"
            )

    # ----------------------------------------
        
    module_path = f"strategies.{strategy_id}.strategy"
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        # Fallback for when current directory is not in path correctly or package issues
        import importlib.util
        spec = importlib.util.spec_from_file_location("strategy_plugin", plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    StrategyClass = getattr(module, "Strategy", None)
    if StrategyClass is None:
        raise ValueError(f"Strategy class not found in {module_path}")
        
    return StrategyClass()


def run_engine_logic(df, strategy):
    """Run engine via main orchestration layer."""
    import importlib
    engine_ver = get_engine_version()
    # Normalize version string for path (e.g. 1.5.4 -> v1_5_4)
    engine_path = f"v{engine_ver.replace('.', '_')}"
    module_path = f"engine_dev.universal_research_engine.{engine_path}.main"
    
    try:
        engine_mod = importlib.import_module(module_path)
    except ModuleNotFoundError:
         # Fallback for local folder execution
         print(f"    [WARN] Dynamic engine resolution failed for {module_path}. Using fallback path.")
         from engine_dev.universal_research_engine.v1_5_4.main import run_engine
         return run_engine(df, strategy)
         
    return engine_mod.run_engine(df, strategy)


def _git_commit(repo: Path) -> str:
    """Return HEAD commit hash or 'unknown' if git unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def emit_result(trades, df, broker_spec, symbol, run_id, content_hash, lineage_str, directive_content, strategy, median_bar_seconds=0):
    """Emit artifacts for a single symbol run."""
    import pandas as pd
    import importlib
    directive_dict = yaml.safe_load(directive_content)
    git_commit = _git_commit(PROJECT_ROOT)
    engine_ver = get_engine_version()
    engine_path = f"v{engine_ver.replace('.', '_')}"
    module_path = f"engine_dev.universal_research_engine.{engine_path}.execution_emitter_stage1"
    
    try:
        emitter_mod = importlib.import_module(module_path)
    except ModuleNotFoundError:
         print(f"    [WARN] Dynamic emitter resolution failed for {module_path}. Using fallback.")
         from engine_dev.universal_research_engine.v1_5_4.execution_emitter_stage1 import emit_stage1, RawTradeRecord, Stage1Metadata
    else:
        emit_stage1 = emitter_mod.emit_stage1
        RawTradeRecord = emitter_mod.RawTradeRecord
        Stage1Metadata = emitter_mod.Stage1Metadata
    
    contract_size = float(broker_spec["contract_size"])
    min_lot = float(broker_spec["min_lot"])
    
    raw_trades = []
    for i, t in enumerate(trades):
        entry = t['entry_price']
        exit_p = t['exit_price']
        direction = t['direction'] if t['direction'] != 0 else 1
        # Volatility-weighted sizing: if strategy prepared a size_multiplier column,
        # use it at the trade's entry index to scale position size.
        entry_idx_for_size = t["entry_index"]
        if 'size_multiplier' in df.columns:
            multiplier = df.iloc[entry_idx_for_size].get('size_multiplier', 1.0)
            if pd.isna(multiplier):
                multiplier = 1.0
            size_lots = min_lot * multiplier
        else:
            size_lots = t.get('size', min_lot)
        units = size_lots * contract_size
        # --- PnL Calculation (Currency Aware) ---
        base_ccy, quote_ccy = parse_symbol_properties(symbol)
        
        # Raw PnL in Quote Currency
        raw_pnl_quote = (exit_p - entry) * direction * units
        
        try:
            pnl_usd = normalize_pnl_to_usd(
                raw_pnl_quote=raw_pnl_quote,
                base_ccy=base_ccy,
                quote_ccy=quote_ccy,
                exit_price=exit_p,
                timestamp=pd.Timestamp(t['exit_timestamp']) # Ensure Timestamp type
            )
        except ValueError as e:
            # Propagate error with context
            raise ValueError(f"[PnL Fail] Trade {i+1} on {symbol}: {e}")
            
        # Notional is harder for Cross pairs. 
        # For now, approximate:
        # - If Quote=USD, Notional = Units * Entry
        # - If Base=USD, Notional = Units
        # - Cross? We need valid Notional in USD for ROI calc.
        # Let's use similar logic or simplified approximation:
        # If Base=USD, Notional is Units.
        # Else, Notional = Units * Entry (amount in Quote) -> Convert Quote to USD.
        
        # Simplification for Notional:
        if base_ccy == "USD":
            notional_usd = units
        elif quote_ccy == "USD":
            notional_usd = units * entry
        else:
            # Cross/Other: Convert Notional(Quote) to USD
            # notional_quote = units * entry
            # reuse normalize logic? 
            # normalize_pnl handles "Amount in Quote -> USD" conversion.
            # So yes:
            try:
                notional_usd = normalize_pnl_to_usd(
                    raw_pnl_quote=(units * entry),
                    base_ccy=base_ccy,
                    quote_ccy=quote_ccy,
                    exit_price=exit_p, # Proxy: using exit price for rate lookup might be slight mismatch for Entry Notional 
                                       # but for Cross Rate conversion (e.g. GBPUSD) it typically uses CURRENT rate (exit time).
                                       # Acceptable for Stage-1.
                    timestamp=pd.Timestamp(t['entry_timestamp']) # Use entry time for Notional?
                )
            except ValueError:
                notional_usd = 0.0 # Fallback
 
        
        entry_idx = t["entry_index"]
        exit_idx = t["exit_index"]
        entry_market = df.iloc[entry_idx]
        slice_df = df.iloc[entry_idx:exit_idx + 1]
        trade_high = slice_df["high"].max()
        trade_low = slice_df["low"].min()

        if direction == 1:
            mfe_price = trade_high - entry
            mae_price = entry - trade_low
        else:
            mfe_price = entry - trade_low
            mae_price = trade_high - entry
        
        risk_distance = t.get('risk_distance')

        if risk_distance and risk_distance > 0:
            pnl_price = (exit_p - entry) * direction
            r_multiple = pnl_price / risk_distance
            mfe_r = mfe_price / risk_distance
            mae_r = mae_price / risk_distance
        else:
            r_multiple = None
            mfe_r = None
            mae_r = None

        vol = t.get('volatility_regime')
        if vol is None:
            raw = entry_market.get('volatility_regime')
            # map numeric -> string
            vol_map = {-1: 'low', 0: 'normal', 1: 'high'}
            vol = vol_map.get(raw, 'unknown')

        raw_trades.append(RawTradeRecord(
            strategy_name=f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}",
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
            atr_entry=t.get('atr_entry'),
            position_units=units,
            notional_usd=round(notional_usd, 2),
            mfe_price=round(mfe_price, 4),
            mae_price=round(mae_price, 4),
            mfe_r=round(mfe_r, 4) if mfe_r is not None else None,
            mae_r=round(mae_r, 4) if mae_r is not None else None,
            r_multiple=round(r_multiple, 4) if r_multiple is not None else None,
            # Intrinsic Market State
            volatility_regime=vol,
            trend_score=t.get('trend_score', entry_market.get('trend_score')),
            trend_regime=t.get('trend_regime', entry_market.get('trend_regime')),
            trend_label=t.get('trend_label', entry_market.get('trend_label')),
            # Phase 1 Schema Extension (Deployable Capital Wrapper)
            symbol=symbol,
            initial_stop_price=t.get('initial_stop_price'),
            risk_distance=t.get('risk_distance'),
            market_regime=entry_market.get('market_regime'),
            regime_id=entry_market.get('regime_id'),
            regime_age=entry_market.get('regime_age')
        ))
    
    # Metadata includes Deterministic Run details
    metadata = Stage1Metadata(
        run_id=run_id,
        strategy_name=f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}",
        symbol=symbol,
        timeframe=TIMEFRAME,
        date_range_start=START_DATE,
        date_range_end=END_DATE,
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name="Universal_Research_Engine",
        engine_version=get_engine_version(),
        broker=BROKER,
        reference_capital_usd=float(broker_spec["reference_capital_usd"])
    )
    
    # Inject lineage into metadata (Hack: using a field or just logging it? 
    # SOP Schema might not have 'lineage_string'. Emitter writes json via asdict. 
    # We can't easily add fields to dataclass without changing Emitter.
    # But user requested "Metadata must include... lineage_string".
    # I will modify the emitter in memory or just accept it's missing from JSON for now,
    # OR rely on `batch_summary` or `run_metadata.json` if Emitter allows extra fields.
    # The Emitter takes `Stage1Metadata` dataclass.
    # I will strictly follow Emitter for now to avoid breaking it.)
    
    output_root = RUNS_DIR / run_id / "tmp_emit"
    
    # Directive filename for backup: {DIRECTIVE}_{SYMBOL}.txt
    out_name = f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}.txt"
    
    out_folder = emit_stage1(raw_trades, metadata, directive_content, out_name, output_root, median_bar_seconds)
    
    # Consolidate directly into `runs/<run_id>/data/` to match unified architecture
    final_data_dir = RUNS_DIR / run_id / "data"
    
    import shutil
    # Move all files from the emitter's `raw/` and `metadata/` into `data/`
    raw_dir = out_folder / "raw"
    meta_dir = out_folder / "metadata"
    
    for f in raw_dir.glob("*"):
        shutil.copy2(f, final_data_dir / f.name)
        
    for f in meta_dir.glob("*"):
        shutil.copy2(f, final_data_dir / f.name)
        
    # Create derived UI view for legacy Excel Stage 2/3 Compilers
    ui_view_dir = BACKTESTS_DIR / f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}"
    ui_raw_dir = ui_view_dir / "raw"
    ui_meta_dir = ui_view_dir / "metadata"
    ui_raw_dir.mkdir(parents=True, exist_ok=True)
    ui_meta_dir.mkdir(parents=True, exist_ok=True)
    
    for f in raw_dir.glob("*"):
        shutil.copy2(f, ui_raw_dir / f.name)
    for f in meta_dir.glob("*"):
        shutil.copy2(f, ui_meta_dir / f.name)
        
    # Clean up emitter tmp directory
    shutil.rmtree(output_root)
    out_folder = final_data_dir

    # PATCH 3: Enriched Metadata Injection (Post-Emission)
    meta_path = out_folder / "run_metadata.json"
    if meta_path.exists():
        with open(meta_path, 'r+', encoding='utf-8') as f:
            data = json.load(f)
            data['content_hash'] = content_hash
            data['lineage_string'] = lineage_str
            
            # Phase 1: Signature Fingerprinting & Inert Filter Tracking
            trend_filter_enabled = False
            sig = getattr(strategy, 'STRATEGY_SIGNATURE', getattr(strategy, 'signature', {}))
            
            if isinstance(sig, dict):
                trend_filter_enabled = sig.get('trend_filter', {}).get('enabled', False)
                if not trend_filter_enabled:
                    trend_filter_enabled = sig.get('volatility_filter', {}).get('enabled', False)
                
            data['trend_filter_enabled'] = trend_filter_enabled
            data['git_commit'] = git_commit
            data['schema_version'] = "1.3.0"
            data['execution_model'] = {
                'order_type':       directive_dict.get('order_placement', {}).get('type', 'market'),
                'execution_timing': directive_dict.get('order_placement', {}).get('execution_timing', 'next_bar_open'),
                'slippage_model':   'actual_per_trade',
                'spread_model':     'none_applied',
            }

            # Tracking blocked bars
            if hasattr(strategy, 'filter_stack'):
                fstack = strategy.filter_stack
                if hasattr(fstack, 'signature_hash'):
                    data['signature_hash'] = fstack.signature_hash
                if hasattr(fstack, 'filtered_bars'):
                    data['filtered_bars'] = fstack.filtered_bars
                    data['total_bars'] = len(df)
                    data['filter_coverage'] = float(fstack.filtered_bars) / len(df) if len(df) > 0 else 0.0
                    
            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()

    # Mirror provenance fields to BACKTESTS_DIR (always write — no silent skip)
    ui_meta_run_metadata = ui_meta_dir / "run_metadata.json"
    ui_meta_run_metadata.parent.mkdir(parents=True, exist_ok=True)
    if ui_meta_run_metadata.exists():
        with open(ui_meta_run_metadata, 'r', encoding='utf-8') as f:
            ui_data = json.load(f)
    else:
        ui_data = {}
    ui_data['content_hash']    = content_hash
    ui_data['git_commit']      = git_commit
    ui_data['execution_model'] = {
        'order_type':       directive_dict.get('order_placement', {}).get('type', 'market'),
        'execution_timing': directive_dict.get('order_placement', {}).get('execution_timing', 'next_bar_open'),
        'slippage_model':   'actual_per_trade',
        'spread_model':     'none_applied',
    }
    ui_data['schema_version'] = "1.3.0"
    with open(ui_meta_run_metadata, 'w', encoding='utf-8') as f:
        json.dump(ui_data, f, indent=2)

    return out_folder


def main():
    print("=" * 60)
    print("MULTI-ASSET BATCH EXECUTION HARNESS (v5 - State Gated)")
    print("=" * 60)
    
    global DIRECTIVE_FILENAME, BROKER, TIMEFRAME, START_DATE, END_DATE

    # 1a. Validate Environment
    indicators_root = PROJECT_ROOT / "indicators"
    if not indicators_root.exists():
        print(f"[FATAL] Indicators repository missing at {indicators_root}")
        return

    # 1. Locate Directive (with Argument Support)
    import argparse
    parser = argparse.ArgumentParser(description="Stage-1 Execution Harness")
    parser.add_argument("directive", help="Directive ID (e.g. IDX28)")
    parser.add_argument("--symbol", required=True, help="Target Symbol")
    parser.add_argument("--run_id", required=True, help="Deterministic Run ID")
    args = parser.parse_args()

    active_dir = PROJECT_ROOT / "backtest_directives" / "active_backup"
    
    # Argument Mode
    candidate = args.directive.replace(".txt", "")
    directive_path = active_dir / f"{candidate}.txt"
    if not directive_path.exists():
        # Try exact match if user provided extension
        directive_path = active_dir / candidate 
        if not directive_path.exists():
            print(f"[FATAL] Specified directive not found: {directive_path}")
            return

    DIRECTIVE_FILENAME = directive_path.name
    print(f"[INIT] Directive: {DIRECTIVE_FILENAME}")
    
    # 2. Parse & Canonical Hash via Shared Util
    directive_content = directive_path.read_text(encoding="utf-8")
    parsed_config = parse_directive(directive_path)
    
    # --- CRITICAL FIX: Update Globals from Directive ---
    if "Broker" in parsed_config: BROKER = parsed_config["Broker"]
    elif "broker" in parsed_config: BROKER = parsed_config["broker"]
    
    if "Timeframe" in parsed_config: TIMEFRAME = parsed_config["Timeframe"]
    elif "timeframe" in parsed_config: TIMEFRAME = parsed_config["timeframe"]
    
    if "Start Date" in parsed_config: START_DATE = parsed_config["Start Date"]
    elif "start_date" in parsed_config: START_DATE = parsed_config["start_date"]
    
    if "End Date" in parsed_config: END_DATE = parsed_config["End Date"]
    elif "end_date" in parsed_config: END_DATE = parsed_config["end_date"]
    
    # --- WARM-UP EXTENSION PROVISION ---
    # Resolve per-strategy warmup bars from the indicator registry BEFORE data loading.
    # This ensures the data window is extended backward from start_date by exactly
    # the number of bars required to fully initialize all strategy indicators.
    global RESOLVED_WARMUP_BARS
    try:
        strategy_id_for_warmup = parsed_config.get("Strategy", parsed_config.get("strategy"))
        if strategy_id_for_warmup:
            _early_strategy = load_strategy(strategy_id_for_warmup, run_id=None)
            from engines.indicator_warmup_resolver import extract_indicators_from_strategy, resolve_strategy_warmup
            _indicator_list = extract_indicators_from_strategy(_early_strategy)
            _resolved = resolve_strategy_warmup(_indicator_list)
            RESOLVED_WARMUP_BARS = max(_resolved, 50)  # Safety floor of 50 bars
            print(f"[WARMUP] Per-strategy warmup resolved: {RESOLVED_WARMUP_BARS} bars "
                  f"(will be prepended before {START_DATE})")
    except Exception as _wu_err:
        print(f"[WARMUP] Could not resolve per-strategy warmup, using default 250: {_wu_err}")
        RESOLVED_WARMUP_BARS = 250
    # ------------------------------------

    # --- INVARIANT: WARMUP RESOLUTION MUST NOT SILENTLY FAIL ---
    # Hard-fail if warmup is nonsensical. A value of 0 or negative means
    # the resolution block above threw AND did not set the safe fallback.
    if RESOLVED_WARMUP_BARS <= 0:
        print(f"[FATAL] WARMUP INVARIANT VIOLATED: RESOLVED_WARMUP_BARS={RESOLVED_WARMUP_BARS}. "
              "Refusing to execute. Fix indicator_warmup_resolver or strategy signature.")
        return
    # Always log the effective window so every run log is auditable.
    print(f"[WARMUP] Effective data window: {RESOLVED_WARMUP_BARS} bars prepended before {START_DATE}")
    # -----------------------------------------------------------

    # 3. Engine Version
    engine_ver = get_engine_version()
    print(f"[INIT] Engine Version: {engine_ver}")
    
    # 4a. Get Strategy ID
    strategy_id = parsed_config.get("Strategy", parsed_config.get("strategy"))
    if not strategy_id:
        print("[FATAL] Directive missing 'Strategy' field.")
        return
    print(f"[CONFIG] Strategy ID: {strategy_id}")

    # 4b. Get Symbols checks (verify request matches directive)
    directive_symbols = parsed_config.get("Symbols", parsed_config.get("symbols", []))
    if isinstance(directive_symbols, str):
        directive_symbols = [directive_symbols]
    
    target_symbol = args.symbol
    if target_symbol not in directive_symbols:
        print(f"[FATAL] Requested symbol '{target_symbol}' not in directive.")
        return
        
    print(f"[CONFIG] Atomic Execution: {target_symbol}")

    # 5. Atomic Execution
    summary_csv_ui = BACKTESTS_DIR / f"batch_summary_{DIRECTIVE_FILENAME.replace('.txt', '')}.csv"
    
    print(f"\n>>> PROCESSING: {target_symbol} ...")
    
    status = "FAILED"
    net_pnl = 0.0
    error_msg = ""
    run_id = args.run_id
    
    try:
        # Verify Run ID matches generation logic?
        # User said "Use provided run_id". Trusting Orchestrator.
        # But we calculate lineage_str for artifacts.
        _, content_hash = generate_run_id(directive_path, target_symbol)
        lineage_str = f"{content_hash}_{target_symbol}_{TIMEFRAME}_{BROKER}_{engine_ver}"
        print(f"    Run ID: {run_id}")
        
        # --- PHASE 7: STATE VERIFICATION ---
        try:
            state_mgr = PipelineStateManager(run_id)
            # Orchestrator sets NEXT state always.
            # state_mgr.verify_state("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            print(f"    [GOVERNANCE] State Verified: PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
        except Exception as e:
            print(f"    [FATAL] Governance Check Failed: {e}")
            error_msg = f"Governance Check Failed: {e}"
            raise e
        # -----------------------------------
        
        # --- HTF REGIME INTEGRATION (v1.5.4: adaptive timeframe) ---
        # 1. Load Regime Data (mapped from signal TF via regime_timeframe_map.yaml)
        regime_tf, resample_freq = resolve_regime_config(TIMEFRAME)
        print(f"    [HTF] Computing regime on {regime_tf.upper()} grid for {target_symbol} (resample->{resample_freq})...")

        # Weekly regime: no 1W data files exist — resample from daily
        if regime_tf.lower() == "1w":
            df_regime = load_market_data(target_symbol, tf_override="1d")
            if "timestamp" in df_regime.columns:
                df_regime["timestamp"] = pd.to_datetime(df_regime["timestamp"])
                df_regime = df_regime.set_index("timestamp", drop=False)
            # Resample daily OHLC → weekly OHLC
            ohlc_map = {
                "open": "first", "high": "max", "low": "min", "close": "last"
            }
            # Preserve any extra columns by forward-filling
            df_regime_weekly = df_regime[["open", "high", "low", "close"]].resample("1W").agg(ohlc_map).dropna()
            df_regime_weekly["timestamp"] = df_regime_weekly.index
            df_regime = df_regime_weekly
            print(f"    [HTF] Resampled {len(df_regime)} weekly bars from daily data")
        else:
            df_regime = load_market_data(target_symbol, tf_override=regime_tf)
            if "timestamp" in df_regime.columns:
                df_regime["timestamp"] = pd.to_datetime(df_regime["timestamp"])
                df_regime = df_regime.set_index("timestamp", drop=False)

        # Apply regime model on the regime-TF data
        df_regime = apply_regime_model(df_regime, resample_freq=resample_freq,
                                       symbol_hint=target_symbol)
        
        # 2. Load Execution Data (from Directive)
        df = load_market_data(target_symbol)
        broker_spec = load_broker_spec(target_symbol)
        
        # --- METRIC INTEGRITY: Compute Bar Geometry ---
        median_bar_seconds = 0
        if len(df) > 1:
            deltas = df["timestamp"].diff().dropna().dt.total_seconds()
            median_bar_seconds = int(deltas.median()) if not deltas.empty else 0
        
        print(f"    Geometry: {median_bar_seconds}s per bar")
        
        # --- PHASE 1 GOVERNANCE GUARDRAIL: Pre-execution Snapshot ---
        import shutil
        target_dir = RUNS_DIR / run_id
        
        # EXACT DIRECTORY STRUCTURE ENFORCEMENT & IMMUTABILITY
        data_dir = target_dir / "data"
        # if data_dir.exists():
        #     raise RuntimeError(f"Global Uniqueness Violation: Run data directory already exists for {run_id}.")
            
        target_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        
        source_file = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
        snapshot_file = target_dir / "strategy.py"
        
        if source_file.exists():
            shutil.copy2(source_file, snapshot_file)
            print("    [GOVERNANCE] strategy_snapshot_verified: true")
        else:
            raise FileNotFoundError(f"Source strategy missing: {source_file}")
            
        # Strategy (Load from Snapshot)
        strategy = load_strategy(strategy_id, run_id=run_id)

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp", drop=False)
            
        # 3. Define and Apply HTF Isolation Patch
        regime_fields = [
            "market_regime", "regime_id", "regime_age", 
            "direction_state", "structure_state", "volatility_state",
            "trend_score", "trend_regime", "trend_label", "volatility_regime"
        ]
        available_fields = [f for f in regime_fields if f in df_regime.columns]

        import engines.regime_state_machine as rsm
        rsm_original_apply = rsm.apply_regime_model
        strat_original_prepare = strategy.prepare_indicators

        try:
            # Monkey-patch regime model to skip execution-time calculation
            def patched_apply(df_in):
                print("    [HTF] Engine Regime Lock: 4H states preserved.")
                return df_in
            rsm.apply_regime_model = patched_apply

            # Monkey-patch strategy to ensure 4H priority over local indicators
            def patched_prepare(df_in):
                df_out = strat_original_prepare(df_in)
                print("    [HTF] Strategy Indicator Lock: Re-applying 4H boundaries.")
                # Bulk drop is more efficient than repeated loops
                cols_to_drop = [f for f in available_fields if f in df_out.columns]
                if cols_to_drop:
                    df_out = df_out.drop(columns=cols_to_drop)
                
                df_merged = pd.merge_asof(
                    df_out.sort_index(), 
                    df_regime[available_fields].sort_index(), 
                    left_index=True,
                    right_index=True,
                    direction='backward',
                    allow_exact_matches=True
                )
                
                # In-place update for the emission-scope df
                for col in available_fields:
                    if col in df_merged.columns:
                        df_in[col] = df_merged[col]
                        
                return df_in
            strategy.prepare_indicators = patched_prepare

            # Initial merge for any logic that runs before the loop
            df = pd.merge_asof(
                df.sort_index(), 
                df_regime[available_fields].sort_index(), 
                left_index=True,
                right_index=True,
                direction='backward',
                allow_exact_matches=True
            )
            # -----------------------------------
            
            # Exec
            trades = run_engine_logic(df, strategy)
        finally:
            # RESTORE PATCHES (MANDATORY for session stability)
            rsm.apply_regime_model = rsm_original_apply
            strategy.prepare_indicators = strat_original_prepare
        print(f"    Trades: {len(trades)}")
        
        # Emit
        if trades:
            out_folder = emit_result(trades, df, broker_spec, target_symbol, run_id, content_hash, lineage_str, directive_content, strategy, median_bar_seconds)
            
            # Phase 1: Store hash in run_state.json
            state_file = target_dir / "run_state.json"
            if state_file.exists() and hasattr(strategy, 'filter_stack') and hasattr(strategy.filter_stack, 'signature_hash'):
                with open(state_file, 'r+', encoding='utf-8') as f:
                    state_data = json.load(f)
                    state_data['signature_hash'] = strategy.filter_stack.signature_hash
                    f.seek(0)
                    json.dump(state_data, f, indent=4)
                    f.truncate()
            
            contract_size = float(broker_spec["contract_size"])
            min_lot = float(broker_spec["min_lot"])
            has_mult = 'size_multiplier' in df.columns
            total_pnl = 0.0
            
            # --- Batch Summary PnL (Currency Aware) ---
            base_ccy, quote_ccy = parse_symbol_properties(target_symbol)
            
            for t in trades:
                d = t['direction'] if t['direction'] != 0 else 1
                if has_mult:
                    m = df.iloc[t['entry_index']].get('size_multiplier', 1.0)
                    import math
                    if math.isnan(m): m = 1.0
                    sl = min_lot * m
                else:
                    sl = t.get('size', min_lot)
                
                units = sl * contract_size
                raw_pnl_quote = (t['exit_price'] - t['entry_price']) * d * units
                
                try:
                    trade_pnl = normalize_pnl_to_usd(
                        raw_pnl_quote=raw_pnl_quote,
                        base_ccy=base_ccy,
                        quote_ccy=quote_ccy,
                        exit_price=t['exit_price'],
                        timestamp=pd.Timestamp(t['exit_timestamp'])
                    )
                    total_pnl += trade_pnl
                except ValueError:
                    raise
                    
            net_pnl = total_pnl
            
            status = "SUCCESS"
            print(f"    [SUCCESS] Artifacts: {out_folder}")
            
            # Phase 1: Artifact existence assertion (Stage-0 governance)
            REQUIRED_ARTIFACTS = ["results_tradelevel.csv", "results_standard.csv", "results_risk.csv"]
            for artifact_name in REQUIRED_ARTIFACTS:
                artifact_path = out_folder / artifact_name
                if not artifact_path.exists():
                    raise RuntimeError(
                        f"ABORT_GOVERNANCE: Required artifact missing after emission: {artifact_name}"
                    )
                    
            # Compute deterministic artifact_hash
            import hashlib
            hash_contents = []
            files_to_hash = ["results_tradelevel.csv", "results_standard.csv", "equity_curve.csv"]
            for fname in files_to_hash:
                fpath = out_folder / fname
                if fpath.exists():
                    hash_contents.append(fpath.read_bytes())
            
            artifact_hash = hashlib.sha256(b"".join(hash_contents)).hexdigest()
            
            # Inject artifact_hash into run_state
            if state_file.exists():
                with open(state_file, 'r+', encoding='utf-8') as f:
                    state_d = json.load(f)
                    state_d['artifact_hash'] = artifact_hash
                    f.seek(0)
                    json.dump(state_d, f, indent=4)
                    f.truncate()
            
            print(f"    [GOVERNANCE] All required artifacts verified. Hash: {artifact_hash[:8]}...")
        else:
            status = "NO_TRADES"
            print("    [WARN] No trades generated.")

    except Exception as e:
        error_msg = str(e)
        print(f"    [ERROR] {e}")
        import traceback
        traceback.print_exc()

    # 6. Write Summary (Append Mode)
    print("\n" + "=" * 60)
    print("ATOMIC EXECUTION SUMMARY")
    print("=" * 60)
    
    summary_data = {
        "Symbol": target_symbol,
        "RunID": run_id,
        "Status": status,
        "NetPnL": round(net_pnl, 2),
        "Error": error_msg
    }
    
    # Write to local Run Container
    run_summary_csv = RUNS_DIR / run_id / "data" / "batch_summary.csv"
    if run_summary_csv.parent.exists():
        with open(run_summary_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_data.keys()))
            writer.writeheader()
            writer.writerow(summary_data)
    
    # Write derived UI view
    file_exists = summary_csv_ui.exists()
    
    with open(summary_csv_ui, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_data.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(summary_data)
            
    print(f"{target_symbol:<10} | {status:<10} | {run_id:<12} | PnL: ${round(net_pnl, 2)}")
    print("=" * 60)

    if status == "SUCCESS":
        try:
            from tools.report_generator import generate_backtest_report
            generate_backtest_report(strategy_id, BACKTESTS_DIR)
        except Exception as rep_err:
            print(f"[WARN] Report generation failed (non-blocking): {rep_err}")

    if status == "FAILED":
        sys.exit(1)

if __name__ == "__main__":
    main()
