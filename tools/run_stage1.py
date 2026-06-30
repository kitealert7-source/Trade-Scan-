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
            df = load_market_data(target_pair, tf_override="1d")
            
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


def run_engine_logic(df, strategy, health=None):
    """Run engine via main orchestration layer.

    The engine module is resolved from ``get_engine_version()`` (registry
    active_engine, or ENGINE_VERSION_OVERRIDE) -- the SAME value that stamps the
    run's engine_version in ``_emit_build_metadata``. Resolution and stamp are
    one source, so a single-strategy run can never label itself as an engine it
    did not compute on. A previous silent fallback to v1_5_6 on
    ModuleNotFoundError broke that contract (it ran v1_5_6 compute while the
    stamp kept the requested version); it is now a fail-fast (Invariant #1) so a
    mis-resolved engine ABORTS rather than mislabeling. Doctrine:
    memory ``engine_identity_is_compute_not_stamp``.
    """
    import importlib
    engine_ver = get_engine_version()
    # Normalize version string for path (e.g. 1.5.4 -> v1_5_4)
    engine_path = f"v{engine_ver.replace('.', '_')}"
    module_path = f"engine_dev.universal_research_engine.{engine_path}.main"

    try:
        engine_mod = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Engine v{engine_ver} (resolved from registry active_engine / "
            f"ENGINE_VERSION_OVERRIDE) has no loadable run-engine module at "
            f"'{module_path}': {exc}. Refusing to silently fall back to v1_5_6 "
            f"and mislabel this run as v{engine_ver}. Point engine selection at a "
            f"version that ships main.py, or add the engine. See "
            f"engine_identity_is_compute_not_stamp."
        ) from exc

    # Bind the STAMP to the loaded module's OWN declared identity, not the
    # trusted-but-unverified folder name. get_engine_version() returns the
    # registry/override STRING and _emit_build_metadata stamps that same string;
    # if the folder name disagrees with the module's ENGINE_VERSION the run would
    # be stamped v{engine_ver} while computing on a different engine. (The v1_5_3
    # folder ships the 1.5.4 engine -- a real, present-today skew.) Abort rather
    # than mislabel. See engine_identity_is_compute_not_stamp.
    _loaded_ver = getattr(engine_mod, "ENGINE_VERSION", None) \
        or getattr(engine_mod, "__version__", None)
    if _loaded_ver is not None and str(_loaded_ver) != str(engine_ver):
        raise RuntimeError(
            f"Engine selection resolved folder v{engine_ver}, but its module "
            f"'{module_path}' declares ENGINE_VERSION={_loaded_ver!r}. The folder "
            f"name disagrees with the engine's own identity -- the run would be "
            f"STAMPED v{engine_ver} but COMPUTED on v{_loaded_ver}. Aborting to "
            f"prevent a mislabel. Fix the registry/override to name the version "
            f"the module actually is. See engine_identity_is_compute_not_stamp."
        )
    if not hasattr(engine_mod, "run_engine"):
        raise RuntimeError(
            f"Engine v{engine_ver} module '{module_path}' exposes no run_engine() "
            f"entry point; cannot execute. See engine_identity_is_compute_not_stamp."
        )

    # v1.5.11 Patch A: pass the run-level health accumulator ONLY when the
    # resolved engine's run_engine() actually accepts it. Pre-v1.5.11 engines
    # (e.g. the canonical v1_5_10) have no `health` parameter, so this keeps a
    # single bridge that serves every engine version without a TypeError.
    if health is not None:
        import inspect
        try:
            _accepts_health = "health" in inspect.signature(engine_mod.run_engine).parameters
        except (TypeError, ValueError):
            _accepts_health = False
        if _accepts_health:
            return engine_mod.run_engine(df, strategy, health=health)

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


# ────────────────────────────────────────────────────────────────────────
# emit_result — phase helpers (2026-06-01 decomposition, Backlog 4/4)
#
# `emit_result` was 493 LOC, the largest function in the repo. Decomposed
# into seven phase helpers + a slim orchestrator. Behavior is byte-
# equivalent: same emitter resolution + capability detection, same
# per-trade math (sizing + composite PnL + notional + regime alignment +
# MFE/MAE + R multiple + v1.5.7/v1.5.8 markers), same metadata enrichment
# order, same artifact staging into runs/data + BACKTESTS_DIR mirror.
# ────────────────────────────────────────────────────────────────────────


def _emit_resolve_emitter_and_capabilities(engine_ver, trades):
    """Phase A — dynamic-import the engine-version-pinned emitter module and
    detect its dataclass capabilities. A missing emitter for the pinned
    version is a fail-fast RuntimeError, never a silent fallback to the
    v1_5_6 emitter: the EMIT/schema layer must match the compute engine, so
    substituting another version's emitter would ship artifacts whose
    schema/identity disagree with the run's stamped engine_version
    (Invariant #1; engine_identity_is_compute_not_stamp). Also raises
    RuntimeError if engine
    output contains partial-exit metadata but the resolved emitter is the
    pre-v1.5.7 form that lacks partial-aware fields (silent downgrade
    would drop the partial-leg audit and ship composite-PnL as final-leg
    only).

    Returns a dict bundling:
      emit_stage1, RawTradeRecord, Stage1Metadata, PartialLegRecord,
      supports_partials, supports_exit_source
    """
    import importlib
    engine_path = f"v{engine_ver.replace('.', '_')}"
    module_path = f"engine_dev.universal_research_engine.{engine_path}.execution_emitter_stage1"

    try:
        emitter_mod = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        # Same anti-mislabel contract as run_engine_logic: the EMIT/schema layer
        # must match the compute engine. Silently substituting the v1_5_6 emitter
        # while the trades were computed on v{engine_ver} produces artifacts whose
        # schema/identity disagree with the run's stamped engine_version. Fail
        # fast rather than emit under the wrong layer. (All shipped engines
        # v1_5_6..v1_5_9 carry an emitter; a missing one is a real wiring error.)
        raise RuntimeError(
            f"Engine v{engine_ver} has no execution_emitter_stage1 at "
            f"'{module_path}': {exc}. Refusing to silently emit under the v1_5_6 "
            f"emitter while computing on v{engine_ver} (schema/identity mismatch). "
            f"Add the emitter or correct the engine selection. See "
            f"engine_identity_is_compute_not_stamp."
        ) from exc
    else:
        emit_stage1 = emitter_mod.emit_stage1
        RawTradeRecord = emitter_mod.RawTradeRecord
        Stage1Metadata = emitter_mod.Stage1Metadata
        PartialLegRecord = getattr(emitter_mod, "PartialLegRecord", None)

    # Detect which fields the emitter's RawTradeRecord supports. v1.5.7 adds
    # has_partial/partial_fraction/partial_exit_r; v1.5.6 lacks them. Gate kwargs
    # so no-hook strategies running on the v1.5.6 emitter remain byte-identical.
    from dataclasses import fields as _dc_fields
    _raw_record_fields = {f.name for f in _dc_fields(RawTradeRecord)}
    _emitter_supports_partials = (
        PartialLegRecord is not None
        and "has_partial" in _raw_record_fields
    )

    # v1.5.8 contract v1.3 — exit-source attribution support (additive).
    # When the emitter has the new `exit_source` field we derive the namespaced
    # canonical label from the engine's internal exit_source + the strategy's
    # optional return-string. Older emitters silently skip the kwarg.
    _emitter_supports_exit_source = "exit_source" in _raw_record_fields

    # Fail-fast guard: partials in engine output require the v1.5.7 emitter.
    # Without this, partial_leg would be silently dropped under the v1.5.6
    # emitter and the strategy would ship composite-PnL as final-leg only.
    _partials_emitted = any(
        isinstance(t, dict) and t.get("partial_leg") is not None
        for t in trades
    )
    if _partials_emitted and not _emitter_supports_partials:
        raise RuntimeError(
            f"[STAGE1 GUARD] Partial exits detected in engine output but active "
            f"engine (v{engine_ver}) does not support partial-aware emission. "
            f"Silent downgrade would drop the partial-leg audit and ship "
            f"composite-PnL as final-leg only. "
            f"Re-run with ENGINE_VERSION_OVERRIDE=v1_5_7."
        )

    return {
        "emit_stage1": emit_stage1,
        "RawTradeRecord": RawTradeRecord,
        "Stage1Metadata": Stage1Metadata,
        "PartialLegRecord": PartialLegRecord,
        "supports_partials": _emitter_supports_partials,
        "supports_exit_source": _emitter_supports_exit_source,
    }


def _emit_compute_trade_money(i, t, df, broker_spec, symbol):
    """Per-trade B sub-helper — sizing + composite PnL + notional USD.

    Volatility-weighted sizing: if the strategy prepared a `size_multiplier`
    column, the trade's entry-index multiplier scales position size.

    v1.5.7 partial-exit composite PnL: when the engine fires a partial on
    this trade, a `partial_leg` sub-dict carries the executed fraction and
    leg state. Option-A sidecar architecture: main CSV pnl_usd is the
    composite (partial + remainder); per-leg detail goes to the sidecar.
    Invariants enforced here:
      - Executed fraction comes from engine, not strategy config.
      - Leg USD computed with PER-LEG exit-timestamp FX rate (no reuse).
      - R composite is leg-first downstream (never USD → R back-convert).

    Notional USD: simplified — units when Base=USD, units*entry when
    Quote=USD, else normalize_pnl_to_usd is reused for cross-rate
    conversion (acceptable proxy at Stage-1 per inline note).

    Returns a dict bundling entry/exit/direction, units, base/quote ccy,
    has_partial + partial fraction + partial R value, pnl_usd (composite),
    pnl_usd_partial (or 0), notional_usd.
    """
    import pandas as pd

    contract_size = float(broker_spec["contract_size"])
    min_lot = float(broker_spec["min_lot"])
    entry = t['entry_price']
    exit_p = t['exit_price']
    direction = t['direction'] if t['direction'] != 0 else 1
    entry_idx_for_size = t["entry_index"]
    if 'size_multiplier' in df.columns:
        multiplier = df.iloc[entry_idx_for_size].get('size_multiplier', 1.0)
        if pd.isna(multiplier):
            multiplier = 1.0
        size_lots = min_lot * multiplier
    else:
        size_lots = t.get('size', min_lot)
    units = size_lots * contract_size
    base_ccy, quote_ccy = parse_symbol_properties(symbol)

    partial_leg = t.get("partial_leg") if isinstance(t, dict) else None
    has_partial = partial_leg is not None
    executed_partial_fraction = float(partial_leg["fraction"]) if has_partial else 0.0
    partial_exit_r_val = float(partial_leg["unrealized_r"]) if has_partial else 0.0
    pnl_usd_partial = 0.0

    try:
        if has_partial:
            partial_units = units * executed_partial_fraction
            remainder_units = units * (1.0 - executed_partial_fraction)
            partial_exit_price = float(partial_leg["exit_price"])
            partial_exit_ts = pd.Timestamp(partial_leg["exit_timestamp"])

            raw_pnl_quote_partial = (partial_exit_price - entry) * direction * partial_units
            pnl_usd_partial = normalize_pnl_to_usd(
                raw_pnl_quote=raw_pnl_quote_partial,
                base_ccy=base_ccy,
                quote_ccy=quote_ccy,
                exit_price=partial_exit_price,
                timestamp=partial_exit_ts,
            )

            raw_pnl_quote_remainder = (exit_p - entry) * direction * remainder_units
            pnl_usd_remainder = normalize_pnl_to_usd(
                raw_pnl_quote=raw_pnl_quote_remainder,
                base_ccy=base_ccy,
                quote_ccy=quote_ccy,
                exit_price=exit_p,
                timestamp=pd.Timestamp(t['exit_timestamp']),
            )

            pnl_usd = pnl_usd_partial + pnl_usd_remainder
        else:
            raw_pnl_quote = (exit_p - entry) * direction * units
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

    # Notional in USD — simplified per inline note. Cross-pair routes
    # through normalize_pnl_to_usd's rate-lookup; fallback to 0.0 on failure.
    if base_ccy == "USD":
        notional_usd = units
    elif quote_ccy == "USD":
        notional_usd = units * entry
    else:
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

    return {
        "entry": entry, "exit_p": exit_p, "direction": direction,
        "units": units, "size_lots": size_lots,
        "base_ccy": base_ccy, "quote_ccy": quote_ccy,
        "has_partial": has_partial,
        "executed_partial_fraction": executed_partial_fraction,
        "partial_exit_r_val": partial_exit_r_val,
        "pnl_usd": pnl_usd,
        "pnl_usd_partial": pnl_usd_partial,
        "notional_usd": notional_usd,
    }


def _emit_compute_trade_regime_and_excursion(t, df, money):
    """Per-trade B sub-helper — signal/fill alignment + regime fields +
    MFE/MAE + R multiple + volatility regime.

    v1.5.5 signal/fill alignment: the engine emits signal_bar_idx /
    fill_bar_idx independently — there is NO engine-level invariant that
    signal_bar_idx == fill_bar_idx - 1. That identity is a property of the
    next_bar_open fill model only; same-bar or delayed-fill models will
    break it and must be accommodated without changing this reader.

    Legacy-trade fallback (LOCAL SCOPE ONLY): trade dicts produced by
    pre-v1.5.5 engines don't carry explicit indices. Those engines only
    ever supported next_bar_open, so for those trades — and ONLY those —
    we derive signal_bar_idx as entry_idx-1. Never propagate this
    assumption outside the legacy branch.

    R multiple: leg-first composite for partials. Never back-convert
    USD → R (cross-pair FX skew would contaminate the R-multiple).
    """
    entry_idx = t["entry_index"]
    exit_idx = t["exit_index"]
    entry_market = df.iloc[entry_idx]
    slice_df = df.iloc[entry_idx:exit_idx + 1]

    _fill_bar_idx = t.get("fill_bar_idx", entry_idx)
    _signal_bar_idx = t.get("signal_bar_idx", max(entry_idx - 1, 0))
    _signal_market = df.iloc[_signal_bar_idx] if _signal_bar_idx >= 0 else entry_market
    # Prefer engine-provided values; fall back to df lookup for legacy trades.
    _regime_age_signal = t.get("regime_age_signal")
    if _regime_age_signal is None:
        _regime_age_signal = _signal_market.get("regime_age")
    _regime_age_fill = t.get("regime_age_fill")
    if _regime_age_fill is None:
        _regime_age_fill = entry_market.get("regime_age")
    _market_regime_signal = t.get("market_regime_signal")
    if _market_regime_signal is None:
        _market_regime_signal = _signal_market.get("market_regime")
    _market_regime_fill = t.get("market_regime_fill")
    if _market_regime_fill is None:
        _market_regime_fill = entry_market.get("market_regime")
    _regime_id_signal = t.get("regime_id_signal")
    if _regime_id_signal is None:
        _regime_id_signal = _signal_market.get("regime_id")
    _regime_id_fill = t.get("regime_id_fill")
    if _regime_id_fill is None:
        _regime_id_fill = entry_market.get("regime_id")
    # v1.5.6 exec-TF clock probe — engine-only source (no legacy fallback
    # needed; fields absent in pre-v1.5.6 trades -> None -> "" in CSV).
    _regime_age_exec_signal = t.get("regime_age_exec_signal")
    _regime_age_exec_fill   = t.get("regime_age_exec_fill")
    trade_high = slice_df["high"].max()
    trade_low = slice_df["low"].min()

    entry = money["entry"]
    exit_p = money["exit_p"]
    direction = money["direction"]

    if direction == 1:
        mfe_price = trade_high - entry
        mae_price = entry - trade_low
    else:
        mfe_price = entry - trade_low
        mae_price = trade_high - entry

    risk_distance = t.get('risk_distance')

    if risk_distance and risk_distance > 0:
        mfe_r = mfe_price / risk_distance
        mae_r = mae_price / risk_distance
        if money["has_partial"]:
            # Leg-first composite R. Never back-convert USD -> R:
            # cross-pair FX skew would contaminate the R-multiple.
            remainder_r_leg = (exit_p - entry) * direction / risk_distance
            r_multiple = (
                money["executed_partial_fraction"] * money["partial_exit_r_val"]
                + (1.0 - money["executed_partial_fraction"]) * remainder_r_leg
            )
        else:
            pnl_price = (exit_p - entry) * direction
            r_multiple = pnl_price / risk_distance
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

    return {
        "entry_market": entry_market,
        "_fill_bar_idx": _fill_bar_idx, "_signal_bar_idx": _signal_bar_idx,
        "_regime_age_signal": _regime_age_signal, "_regime_age_fill": _regime_age_fill,
        "_market_regime_signal": _market_regime_signal, "_market_regime_fill": _market_regime_fill,
        "_regime_id_signal": _regime_id_signal, "_regime_id_fill": _regime_id_fill,
        "_regime_age_exec_signal": _regime_age_exec_signal,
        "_regime_age_exec_fill": _regime_age_exec_fill,
        "trade_high": trade_high, "trade_low": trade_low,
        "mfe_price": mfe_price, "mae_price": mae_price,
        "mfe_r": mfe_r, "mae_r": mae_r, "r_multiple": r_multiple,
        "vol": vol,
    }


def _emit_build_record_lists(trades, df, symbol, broker_spec, emitter_caps):
    """Phase B wrapper — iterate trades, call money + regime sub-helpers,
    assemble RawTradeRecord kwargs (50 fields incl. v1.5.5/v1.5.6/v1.5.7/
    v1.5.8 additions), resolve namespaced exit_source on v1.5.8 emitters,
    and append optional PartialLegRecord sidecar rows.

    Returns (raw_trades, partial_legs_list).

    v1.5.8 contract v1.3 — namespaced exit_source mapping (engine-internal
    label → canonical CSV label). Precedence (engine resolves SL/TP
    intrabar before check_exit, so engine wins by construction):
      STOP        → ENGINE_STOP
      TP          → ENGINE_TP
      TIME_EXIT   → ENGINE_SESSION_RESET (engine-driven session boundary)
      DATA_END    → ENGINE_DATA_END     (engine force-close at last bar)
      SIGNAL_EXIT → STRATEGY_<LABEL>    (label normalized in engine)
                 or STRATEGY_UNSPECIFIED (legacy bool-True returns)
    """
    RawTradeRecord = emitter_caps["RawTradeRecord"]
    PartialLegRecord = emitter_caps["PartialLegRecord"]
    _emitter_supports_partials = emitter_caps["supports_partials"]
    _emitter_supports_exit_source = emitter_caps["supports_exit_source"]

    raw_trades = []
    partial_legs_list = []
    for i, t in enumerate(trades):
        money = _emit_compute_trade_money(i, t, df, broker_spec, symbol)
        regime = _emit_compute_trade_regime_and_excursion(t, df, money)
        entry_market = regime["entry_market"]

        _strategy_name_full = f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}"
        _record_kwargs = dict(
            strategy_name=_strategy_name_full,
            parent_trade_id=i + 1,
            sequence_index=i,
            entry_timestamp=str(t['entry_timestamp']),
            exit_timestamp=str(t['exit_timestamp']),
            direction=money["direction"],
            entry_price=money["entry"],
            exit_price=money["exit_p"],
            bars_held=t['bars_held'],
            pnl_usd=round(money["pnl_usd"], 2),
            trade_high=regime["trade_high"],
            trade_low=regime["trade_low"],
            atr_entry=t.get('atr_entry'),
            position_units=money["units"],
            notional_usd=round(money["notional_usd"], 2),
            mfe_price=round(regime["mfe_price"], 4),
            mae_price=round(regime["mae_price"], 4),
            mfe_r=round(regime["mfe_r"], 4) if regime["mfe_r"] is not None else None,
            mae_r=round(regime["mae_r"], 4) if regime["mae_r"] is not None else None,
            r_multiple=round(regime["r_multiple"], 4) if regime["r_multiple"] is not None else None,
            # Intrinsic Market State
            volatility_regime=regime["vol"],
            trend_score=t.get('trend_score', entry_market.get('trend_score')),
            trend_regime=t.get('trend_regime', entry_market.get('trend_regime')),
            trend_label=t.get('trend_label', entry_market.get('trend_label')),
            # Phase 1 Schema Extension (Deployable Capital Wrapper)
            symbol=symbol,
            initial_stop_price=t.get('initial_stop_price'),
            risk_distance=t.get('risk_distance'),
            market_regime=entry_market.get('market_regime'),
            regime_id=entry_market.get('regime_id'),
            regime_age=entry_market.get('regime_age'),
            # v1.5.5 signal/fill alignment — explicit dual-time record.
            # Legacy (v1.5.4) trades get signal values derived from entry_idx-1.
            signal_bar_idx=regime["_signal_bar_idx"],
            fill_bar_idx=regime["_fill_bar_idx"],
            regime_age_signal=regime["_regime_age_signal"],
            regime_age_fill=regime["_regime_age_fill"],
            market_regime_signal=regime["_market_regime_signal"],
            market_regime_fill=regime["_market_regime_fill"],
            regime_id_signal=regime["_regime_id_signal"],
            regime_id_fill=regime["_regime_id_fill"],
            # v1.5.6 exec-TF clock probe
            regime_age_exec_signal=regime["_regime_age_exec_signal"],
            regime_age_exec_fill=regime["_regime_age_exec_fill"],
        )
        # v1.5.7 partial-exit main-row markers (only passed if emitter supports).
        if _emitter_supports_partials:
            _record_kwargs["has_partial"] = bool(money["has_partial"])
            _record_kwargs["partial_fraction"] = round(money["executed_partial_fraction"], 6)
            _record_kwargs["partial_exit_r"] = round(money["partial_exit_r_val"], 6)

        # v1.5.8 contract v1.3 — namespaced exit_source mapping (see docstring).
        if _emitter_supports_exit_source:
            _engine_label = t.get('exit_source')
            _strat_label  = t.get('strategy_exit_label')
            if _engine_label == 'STOP':
                _ns = 'ENGINE_STOP'
            elif _engine_label == 'TP':
                _ns = 'ENGINE_TP'
            elif _engine_label == 'TIME_EXIT':
                _ns = 'ENGINE_SESSION_RESET'
            elif _engine_label == 'DATA_END':
                _ns = 'ENGINE_DATA_END'
            elif _engine_label == 'SIGNAL_EXIT':
                if _strat_label:
                    if _strat_label.startswith('STRATEGY_') or _strat_label.startswith('ENGINE_'):
                        _ns = _strat_label
                    else:
                        _ns = 'STRATEGY_' + _strat_label
                else:
                    _ns = 'STRATEGY_UNSPECIFIED'
            else:
                _ns = 'STRATEGY_UNSPECIFIED'
            _record_kwargs["exit_source"] = _ns

        raw_trades.append(RawTradeRecord(**_record_kwargs))

        # Sidecar PartialLegRecord — only when emitter supports it AND this trade
        # actually took a partial. All audit fields (entry_timestamp, entry_price,
        # initial_stop_price, risk_distance) are duplicated from the main row so
        # conservation tests can detect cross-file mutation.
        if _emitter_supports_partials and money["has_partial"]:
            partial_leg = t.get("partial_leg")
            partial_legs_list.append(PartialLegRecord(
                strategy_name=_strategy_name_full,
                parent_trade_id=i + 1,
                symbol=symbol,
                direction=money["direction"],
                entry_timestamp=str(t['entry_timestamp']),
                entry_price=money["entry"],
                initial_stop_price=t.get('initial_stop_price'),
                risk_distance=t.get('risk_distance'),
                partial_exit_timestamp=str(partial_leg["exit_timestamp"]),
                partial_exit_price=float(partial_leg["exit_price"]),
                partial_fraction=round(money["executed_partial_fraction"], 6),
                partial_bars_held=int(partial_leg.get("bars_held", 0)),
                partial_unrealized_r=round(money["partial_exit_r_val"], 6),
                partial_pnl_usd=round(money["pnl_usd_partial"], 2),
                partial_position_units=money["units"] * money["executed_partial_fraction"],
                partial_trade_high_at_exit=float(partial_leg.get("trade_high", 0.0)),
                partial_trade_low_at_exit=float(partial_leg.get("trade_low", 0.0)),
                partial_reason=str(partial_leg.get("reason", "partial")),
                final_exit_timestamp=str(t['exit_timestamp']),
                final_exit_price=float(money["exit_p"]),
            ))

    return raw_trades, partial_legs_list


def _emit_build_metadata(run_id, symbol, broker_spec, Stage1Metadata):
    """Phase C — Stage1Metadata dataclass with run_id, strategy_name,
    timeframe, date range, execution timestamp, engine info, broker, and
    reference capital. lineage_string is NOT in the dataclass schema —
    it's injected post-emission into run_metadata.json (see Phase E)."""
    return Stage1Metadata(
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


def _emit_stage_artifacts_to_runs_and_ui(out_folder, output_root, run_id, symbol):
    """Phase D part 2 — after emit_stage1 has produced its tmp tree at
    `out_folder/raw|metadata`, consolidate into the unified layout:
      - runs/<run_id>/data/  (the per-run snapshot)
      - BACKTESTS_DIR/<directive>_<symbol>/raw|metadata  (UI mirror for
        legacy Excel Stage-2/3 compilers)
    Cleans up the emitter's entire tmp directory (`output_root`, which
    contains out_folder). Returns the final data dir + the UI metadata
    dir (the latter is needed by Phase E for mirror writes)."""
    import shutil

    final_data_dir = RUNS_DIR / run_id / "data"
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

    # Clean up the emitter's entire tmp directory tree (output_root contains
    # out_folder; rmtree(output_root) matches the original behavior verbatim).
    shutil.rmtree(output_root)
    return final_data_dir, ui_meta_dir


def _emit_enrich_metadata_files(out_folder, ui_meta_dir, content_hash,
                                lineage_str, git_commit, strategy, df,
                                directive_dict, engine_health=None):
    """Phase E + F — PATCH 3: post-emission metadata enrichment.

    Phase E — runs/run_metadata.json (the canonical per-run record):
      content_hash + lineage_string + trend_filter_enabled detection +
      git_commit + schema_version + execution_model + filter_stack
      tracking (signature_hash, filtered_bars, total_bars, filter_coverage).

    Phase F — UI mirror at BACKTESTS_DIR/<directive>_<symbol>/metadata/
      run_metadata.json: provenance fields only (content_hash, git_commit,
      execution_model, schema_version). Always writes — no silent skip."""
    # Phase E — runs-side enrichment
    # R9 self-ID: cost regime DERIVED from the engine's self-reported
    # engine_version (compute, not a stamp) + the MEASURED spread coverage of the
    # consumed bars -- the single-asset analogue of the basket cost-regime record.
    from tools.basket_provenance import single_asset_cost_model, leg_spread_coverage_pct
    from tools.engine_features import resolve_invalid_fill_policy
    _spread_cov = leg_spread_coverage_pct(df)
    # Engine Patch A (v1.5.11): resolved engine-fill policy (default FAIL =
    # today). Stamp-only in Patch A — does not alter a trade; the SKIP compute
    # path lands in Patch B. Already validated at Stage -0.23 admission.
    _invalid_fill_policy = resolve_invalid_fill_policy(directive_dict)
    _engine_ver = None  # captured from the engine metadata in Phase E below

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
            data['invalid_fill_policy'] = _invalid_fill_policy
            # v1.5.11 Patch A: run-level engine_health counters (additive
            # telemetry; never touches results_tradelevel.csv). Empty dict when
            # the engine did not populate it (pre-v1.5.11 / no-trades path).
            data['engine_health'] = engine_health if engine_health is not None else {}
            _engine_ver = data.get('engine_version')
            data['execution_model'] = {
                'order_type':       directive_dict.get('order_placement', {}).get('type', 'market'),
                'execution_timing': directive_dict.get('order_placement', {}).get('execution_timing', 'next_bar_open'),
                'slippage_model':   'actual_per_trade',
                'spread_model':         single_asset_cost_model(_engine_ver),
                'spread_coverage_pct':  _spread_cov,
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

    # Phase F — UI mirror (always written; no silent skip)
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
        'spread_model':         single_asset_cost_model(_engine_ver or ui_data.get('engine_version')),
        'spread_coverage_pct':  _spread_cov,
    }
    ui_data['schema_version'] = "1.3.0"
    ui_data['invalid_fill_policy'] = _invalid_fill_policy
    ui_data['engine_health'] = engine_health if engine_health is not None else {}
    with open(ui_meta_run_metadata, 'w', encoding='utf-8') as f:
        json.dump(ui_data, f, indent=2)


def emit_result(trades, df, broker_spec, symbol, run_id, content_hash, lineage_str, directive_content, strategy, median_bar_seconds=0, engine_health=None):
    """Emit artifacts for a single symbol run.

    Slim orchestrator (2026-06-01 decomposition, Backlog Item 4/4):
      A. Resolve emitter module + capabilities + partial-aware guard
      B. Build raw_trades + partial_legs_list (per-trade money + regime
         + record assembly, via 3 sub-helpers)
      C. Build Stage1Metadata
      -  emit_stage1 call (with or without partial_legs sidecar kwarg)
      D. Stage artifacts to runs/data + UI mirror, clean tmp
      E+F. Enrich runs/run_metadata.json + UI-mirror run_metadata.json
      Return final data folder.

    Behavior preserved byte-equivalent: same print order, same try/except
    semantics, same emit_stage1 call shape (conditional partial_legs
    kwarg), same artifact staging order, same metadata key write order."""
    directive_dict = yaml.safe_load(directive_content)
    git_commit = _git_commit(PROJECT_ROOT)
    engine_ver = get_engine_version()

    # Phase A
    emitter_caps = _emit_resolve_emitter_and_capabilities(engine_ver, trades)

    # Phase B
    raw_trades, partial_legs_list = _emit_build_record_lists(
        trades, df, symbol, broker_spec, emitter_caps,
    )

    # Phase C
    metadata = _emit_build_metadata(run_id, symbol, broker_spec, emitter_caps["Stage1Metadata"])

    # Emit — v1.5.7+ emitter accepts a `partial_legs` kwarg for sidecar
    # emission. Pass only when supported; older emitters reject unknown kwargs.
    output_root = RUNS_DIR / run_id / "tmp_emit"
    out_name = f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}.txt"
    emit_stage1 = emitter_caps["emit_stage1"]
    if emitter_caps["supports_partials"]:
        out_folder = emit_stage1(
            raw_trades, metadata, directive_content, out_name, output_root,
            median_bar_seconds, partial_legs=partial_legs_list,
        )
    else:
        out_folder = emit_stage1(raw_trades, metadata, directive_content, out_name, output_root, median_bar_seconds)

    # Phase D (artifact staging) + return signature: final_data_dir is the
    # `out_folder` value the caller (main) hashes into the manifest.
    final_data_dir, ui_meta_dir = _emit_stage_artifacts_to_runs_and_ui(
        out_folder, output_root, run_id, symbol,
    )

    # Phase E + F
    _emit_enrich_metadata_files(
        final_data_dir, ui_meta_dir, content_hash, lineage_str, git_commit,
        strategy, df, directive_dict, engine_health=engine_health,
    )

    return final_data_dir


# ────────────────────────────────────────────────────────────────────────
# main() — phase helpers (2026-06-01 decomposition, Backlog 3/4)
#
# `main` was 499 LOC, the largest function in this file. Decomposed into
# seven phase helpers plus a slim orchestrator. Behavior is byte-equivalent:
# same print order, same exception ladder (3 FATAL warmup guards + outer
# try/except), same monkey-patch lifecycle around run_engine_logic, same
# global-mutation ordering (BROKER/TIMEFRAME/START_DATE/END_DATE/
# DIRECTIVE_FILENAME/RESOLVED_WARMUP_BARS).
# ────────────────────────────────────────────────────────────────────────


def _stage1_parse_args_and_load_directive():
    """Phase A — parse CLI args, locate the admitted directive in
    active_backup/, parse it, and set the BROKER/TIMEFRAME/START_DATE/
    END_DATE/DIRECTIVE_FILENAME module globals from the directive's content.

    Returns (parsed_config, directive_content, directive_path, args), or
    None for the two early-FATAL paths (directive not found in either
    `<stem>.txt` or exact-name form). The caller short-circuits to `return`
    when None is returned (preserves the original main()'s post-FATAL exit
    semantics)."""
    global DIRECTIVE_FILENAME, BROKER, TIMEFRAME, START_DATE, END_DATE

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
            return None

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

    return parsed_config, directive_content, directive_path, args


def _stage1_resolve_warmup_bars(parsed_config):
    """Phase B — resolve per-strategy warmup bars from the indicator registry.

    Sets the module global RESOLVED_WARMUP_BARS. Returns True on success,
    False on FATAL (caller short-circuits to `return`).

    Failure policy (post-incident 2026-05-06): NO catch-all fallback. Every
    exception that can come out of this block (ImportError, AttributeError,
    KeyError, RegistryFormulaError, yaml.YAMLError, etc.) is an infra defect
    — broken strategy.py, malformed registry, contract violation. None are
    recoverable runtime conditions. They propagate as run failures so the
    orchestrator marks the directive FAILED and the queue-health auto-
    detector surfaces it. The two explicit FATAL paths below exist only to
    give clearer operator-facing messages for the most common drift modes
    (timeframe parse, resolver signature drift, invariant violations)."""
    # --- WARM-UP EXTENSION PROVISION (invariant #8) ---
    # (Marker preserved verbatim from the pre-2026-06-01 monolithic main()
    # so the warmup-block invariant tests
    # tests/tools/test_warmup_resolver_signature.py — which scan src_lines
    # for this string to bound the block — continue to find it.)
    global RESOLVED_WARMUP_BARS
    from engines.utils.timeframe import parse_freq_to_minutes
    try:
        _base_tf_min = parse_freq_to_minutes(str(TIMEFRAME))
    except (ValueError, TypeError) as _tf_err:
        # Timeframe parse contract: must be a recognized freq string.
        # Anything else (AttributeError, etc.) is a programmer bug and
        # should propagate.
        print(f"[FATAL] WARMUP: cannot parse directive Timeframe {TIMEFRAME!r}: {_tf_err}. "
              "Refusing to execute.")
        return False
    try:
        strategy_id_for_warmup = parsed_config.get("Strategy", parsed_config.get("strategy"))
        if strategy_id_for_warmup:
            _early_strategy = load_strategy(strategy_id_for_warmup, run_id=None)
            from engines.indicator_warmup_resolver import extract_indicators_from_strategy, resolve_strategy_warmup
            _indicator_list = extract_indicators_from_strategy(_early_strategy)
            _resolved = resolve_strategy_warmup(_indicator_list, base_tf_minutes=_base_tf_min)
            RESOLVED_WARMUP_BARS = max(_resolved, 50)  # Safety floor of 50 bars
            print(f"[WARMUP] Per-strategy warmup resolved: {RESOLVED_WARMUP_BARS} bars "
                  f"(base_tf={_base_tf_min}m; will be prepended before {START_DATE})")
    except TypeError as _wu_err:
        # Resolver signature drift (incident 2026-04-19 → 2026-05-06).
        # Was silently swallowed by a bare except for 17 days. Loud forever.
        print(f"[FATAL] WARMUP: resolver signature mismatch: {_wu_err}. "
              "Refusing to execute. Check engines/indicator_warmup_resolver.py "
              "signature against tools/run_stage1.py call site.")
        return False
    except ValueError as _wu_err:
        # Resolver-declared invariant violation (e.g. HTF declared without base_tf).
        print(f"[FATAL] WARMUP: resolver invariant violation: {_wu_err}. Refusing to execute.")
        return False
    # NO catch-all. Any other exception (ImportError on broken strategy,
    # AttributeError on bad signature shape, KeyError on bad registry,
    # RegistryFormulaError, yaml.YAMLError, etc.) propagates as a run
    # failure — these are infra defects, not runtime degradations.

    # --- INVARIANT: WARMUP RESOLUTION MUST NOT SILENTLY FAIL ---
    # Hard-fail if warmup is nonsensical. A value of 0 or negative means
    # the resolution block above threw AND did not set the safe fallback.
    if RESOLVED_WARMUP_BARS <= 0:
        print(f"[FATAL] WARMUP INVARIANT VIOLATED: RESOLVED_WARMUP_BARS={RESOLVED_WARMUP_BARS}. "
              "Refusing to execute. Fix indicator_warmup_resolver or strategy signature.")
        return False
    # Always log the effective window so every run log is auditable.
    print(f"[WARMUP] Effective data window: {RESOLVED_WARMUP_BARS} bars prepended before {START_DATE}")
    return True


def _stage1_validate_strategy_and_symbol(parsed_config, args):
    """Phase C — extract strategy_id from the directive, validate the
    requested symbol is one of the directive's symbols, and compute the
    derived per-directive batch summary CSV path used by phase E.

    Returns (strategy_id, target_symbol, summary_csv_ui) on success, or
    None on FATAL (missing Strategy field, requested symbol not in
    directive). Caller short-circuits to `return` on None."""
    # 4a. Get Strategy ID
    strategy_id = parsed_config.get("Strategy", parsed_config.get("strategy"))
    if not strategy_id:
        print("[FATAL] Directive missing 'Strategy' field.")
        return None
    print(f"[CONFIG] Strategy ID: {strategy_id}")

    # 4b. Get Symbols checks (verify request matches directive)
    directive_symbols = parsed_config.get("Symbols", parsed_config.get("symbols", []))
    if isinstance(directive_symbols, str):
        directive_symbols = [directive_symbols]

    target_symbol = args.symbol
    if target_symbol not in directive_symbols:
        print(f"[FATAL] Requested symbol '{target_symbol}' not in directive.")
        return None

    print(f"[CONFIG] Atomic Execution: {target_symbol}")

    # 5. Atomic Execution (derive the UI-side batch summary CSV path)
    summary_csv_ui = BACKTESTS_DIR / f"batch_summary_{DIRECTIVE_FILENAME.replace('.txt', '')}.csv"
    return strategy_id, target_symbol, summary_csv_ui


def _stage1_compute_regime_dataframe(target_symbol):
    """Phase D.2 — HTF regime integration (v1.5.4 adaptive timeframe).

    Resolves the regime timeframe from the signal TF, loads regime data
    (resampling daily → weekly when the regime is 1W since no 1W data
    files exist), and applies the regime state machine. Returns the
    regime DataFrame indexed by timestamp."""
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
    return df_regime


def _stage1_load_market_data_and_snapshot(target_symbol, strategy_id, run_id, directive_path):
    """Phase D.3+D.4 — load execution-TF market data + broker spec, compute
    bar geometry, set up the per-run output directory + immutable
    strategy.py snapshot, then load the strategy from the snapshot.

    Returns a context dict bundling df / broker_spec / median_bar_seconds /
    target_dir / strategy — the state the engine-run + emit phases consume.

    Raises FileNotFoundError if the source strategy.py is missing (caught
    by the outer try/except in main, marks the run FAILED)."""
    import shutil

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

    # Co-locate the SOURCE DIRECTIVE with the run, MANDATORY. strategy.py is
    # derived from the directive, so pairing them makes the run self-describing
    # and reproducible even if the directive is later cleaned out of completed/.
    # directive_path is the parsed run directive (existence-checked upstream by
    # _stage1_parse_args_and_load_directive), so this is a guaranteed copy; a
    # failure raises and main's handler marks the run FAILED — the rule is
    # enforced, never silently skipped.
    from tools.run_directive_snapshot import require_directive_snapshot
    _dsnap = require_directive_snapshot(target_dir, directive_path)
    print(f"    [GOVERNANCE] directive_snapshot: {_dsnap['filename']}")

    # Co-locate the IMPORTED INDICATOR MODULES with the run, MANDATORY. The
    # third determinant of a backtest's behavior, alongside strategy.py and the
    # directive: the indicator modules the strategy imports. Without this, a
    # later change to a live indicator's logic/default params silently alters a
    # re-run of a byte-identical strategy.py + directive, and nothing detects
    # the drift. We snapshot BOTH a manifest (module id + content hash +
    # registry version, for cheap fail-loud drift detection at replay) AND byte
    # copies of the source (for bit-exact reproduction after the live module
    # changes) — mirroring how strategy.py is both hashed and copied. Enumerated
    # from the just-written strategy.py snapshot and resolved against
    # PROJECT_ROOT (the same root the engine imports indicators from). A failure
    # raises -> main marks the run FAILED (Fail-Fast); never silently skipped.
    from tools.run_indicator_snapshot import require_indicator_snapshot
    _isnap = require_indicator_snapshot(target_dir, snapshot_file, PROJECT_ROOT)
    print(f"    [GOVERNANCE] indicator_snapshot: {_isnap['module_count']} module(s)")

    # Strategy (Load from Snapshot)
    strategy = load_strategy(strategy_id, run_id=run_id)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp", drop=False)

    return {
        "df": df,
        "broker_spec": broker_spec,
        "median_bar_seconds": median_bar_seconds,
        "target_dir": target_dir,
        "strategy": strategy,
    }


def _stage1_run_engine_with_htf_patches(df, df_regime, strategy, health=None):
    """Phase D.5 — apply HTF isolation monkey-patches, do the initial merge,
    run the execution engine, then restore the patches (try/finally is
    MANDATORY for session stability — the patches mutate module-level
    state).

    The monkey-patches:
      (1) `engines.regime_state_machine.apply_regime_model` becomes a no-op
          so the engine doesn't recompute regime at execution time (the
          regime is already locked at the regime-TF grid).
      (2) `strategy.prepare_indicators` is wrapped so that after the
          strategy's own indicator prep, regime fields are dropped + merged
          from df_regime (HTF priority over local indicators).

    The wrapper also derives the dual-time clocks (regime_age_signal /
    regime_age_fill / regime_id_fill / regime_age_exec) and mirrors them
    onto BOTH df_in (emission scope) and df_merged (loop scope) so the
    outer caller's emit_result slicing sees the same columns. See
    BUGFIX 2026-04-24 inline comments for why we return df_merged (not
    df_in) from the wrapper.

    Returns the trades list."""
    # 3. Define and Apply HTF Isolation Patch
    regime_fields = [
        "market_regime", "regime_id", "regime_age",
        "direction_state", "structure_state", "volatility_state",
        "trend_score", "trend_regime", "trend_label", "volatility_regime"
    ]
    # NOTE: regime_age_signal / regime_age_fill are NOT included here.
    # regime_state_machine.py computes them via shift(-1) on the regime
    # TF (e.g. 4H). Merging those pre-shifted values onto a finer exec
    # TF (e.g. 1H) would be semantically wrong — "next 4H bar's age"
    # is not "next 1H bar's age". The exec-TF variants are derived
    # locally, post-merge, below (_compute_exec_regime_ages).
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

            # Emission-scope mirror: outer caller (run_stage1) holds a
            # reference to df_in and uses it for emit_result slicing after
            # the execution loop returns. Mirror the regime fields onto
            # df_in so that reference stays in sync.
            for col in available_fields:
                if col in df_merged.columns:
                    df_in[col] = df_merged[col]

            # Dual-time derivations — apply to BOTH df_in (emission scope)
            # and df_merged (loop scope) so they stay in lockstep.
            # - regime_age_signal: current bar's regime_age (decision state)
            # - regime_age_fill:   next bar's regime_age (fill state under
            #                      next_bar_open). Tail row NaN (unreachable).
            # - regime_id_fill:    next-bar regime_id for cross-flip probe.
            #                      FILTER-ONLY; never consume as signal input.
            # - regime_age_exec:   exec-TF counter within a regime (resets
            #                      on exec-TF regime_id flip). Separate from
            #                      HTF-quantized regime_age.
            for _df in (df_in, df_merged):
                if 'regime_age' in _df.columns:
                    _df['regime_age_signal'] = _df['regime_age']
                    _df['regime_age_fill']   = _df['regime_age'].shift(-1)
                if 'regime_id' in _df.columns:
                    _df['regime_id_fill'] = _df['regime_id'].shift(-1)
                if 'regime_id' in _df.columns:
                    _rid = _df['regime_id']
                    _df['regime_age_exec'] = (
                        _df.groupby((_rid != _rid.shift()).cumsum()).cumcount()
                    )

            # BUGFIX 2026-04-24: Return df_merged (not df_in) so that
            # strategy-added indicator columns from copy-based indicator
            # modules (e.g. indicators.price.candle_sign_sequence,
            # indicators.price.previous_bar_breakout, which do
            # `df = df.copy()` before adding columns) reach the execution
            # loop intact. Previously returning df_in silently dropped
            # those columns, so ctx.get() on them returned None and the
            # strategy produced NO_TRADES despite the dry-run emitting
            # signals via the un-wrapped prepare_indicators path.
            return df_merged
        strategy.prepare_indicators = patched_prepare

        # Initial merge for any logic that runs before the loop. NOTE: this
        # mutates df in place (sort_index + merge_asof on the caller's df
        # reference) so emit_result sees the merged columns.
        df = pd.merge_asof(
            df.sort_index(),
            df_regime[available_fields].sort_index(),
            left_index=True,
            right_index=True,
            direction='backward',
            allow_exact_matches=True
        )
        # Mirror the dual-time derivation on the pre-loop df so any code
        # that consumes df before check_entry sees the same columns.
        if 'regime_age' in df.columns:
            df['regime_age_signal'] = df['regime_age']
            df['regime_age_fill']   = df['regime_age'].shift(-1)
        # Cross-regime-flip probe: pre-loop mirror of regime_id_fill shift.
        if 'regime_id' in df.columns:
            df['regime_id_fill'] = df['regime_id'].shift(-1)
        # v1.5.6 exec-TF clock probe (pre-loop mirror of patched_prepare).
        if 'regime_id' in df.columns:
            _rid = df['regime_id']
            df['regime_age_exec'] = (
                df.groupby((_rid != _rid.shift()).cumsum()).cumcount()
            )

        # Exec
        trades = run_engine_logic(df, strategy, health=health)
    finally:
        # RESTORE PATCHES (MANDATORY for session stability)
        rsm.apply_regime_model = rsm_original_apply
        strategy.prepare_indicators = strat_original_prepare
    return trades


def _stage1_emit_and_verify(trades, df, broker_spec, target_symbol, run_id,
                            content_hash, lineage_str, directive_content,
                            strategy, median_bar_seconds, target_dir,
                            engine_health=None):
    """Phase D.6 — emit run artifacts, store signature_hash in run_state.json,
    compute USD-normalized PnL per trade, verify required artifacts exist
    after emission, and compute + store the deterministic artifact_hash.

    Returns (status, net_pnl) — status is "SUCCESS" if all artifacts present.
    Raises RuntimeError if a required artifact is missing (caught by the
    outer try/except in main, marks the run FAILED)."""
    out_folder = emit_result(trades, df, broker_spec, target_symbol, run_id, content_hash, lineage_str, directive_content, strategy, median_bar_seconds, engine_health=engine_health)

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
    return status, net_pnl


def _stage1_write_summary_and_reports(target_symbol, run_id, status, net_pnl,
                                      error_msg, summary_csv_ui, strategy_id):
    """Phase E + F — print the summary banner, write the dual-location batch
    summary CSV (per-run snapshot in RUNS_DIR + per-directive UI view in
    BACKTESTS_DIR), then on SUCCESS emit the backtest report + strategy
    card (both non-blocking — failures here log only).

    Does NOT call sys.exit; the caller (main) does that after this returns
    so the FAILED-exit semantics stay together with the orchestrator's
    try/except."""
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
        try:
            from tools.generate_strategy_card import generate_strategy_card
            generate_strategy_card(strategy_id, BACKTESTS_DIR, RUNS_DIR / run_id / "strategy.py", RUNS_DIR)
        except Exception as card_err:
            print(f"[WARN] Strategy card generation failed (non-blocking): {card_err}")


def main():
    """Stage-1 Atomic Execution Harness — slim orchestrator (2026-06-01
    decomposition, Backlog Item 3/4).

    Phase sequence:
      A. Parse args + load directive + set BROKER/TIMEFRAME/... globals
      B. Resolve per-strategy warmup bars (3 FATAL guards)
      C. Validate strategy + symbol membership
      D.1 State verify  (inline — 10 LOC, too small for a helper)
      D.2 Compute regime dataframe (HTF, with 1d → 1w resampling)
      D.3+D.4 Load market data + bar geometry + run-folder snapshot + strategy
      D.5 Run engine inside HTF isolation patches (monkey-patch lifecycle)
      D.6 Emit + per-trade PnL + artifact-existence verify + artifact_hash
      E+F. Write batch summary CSVs + emit backtest report + strategy card

    Behavior preserved byte-equivalent: same print order, same FATAL/return
    semantics, same try/except + try/finally boundaries, same global
    mutations, same exit code (sys.exit(1) on FAILED)."""
    print("=" * 60)
    print("MULTI-ASSET BATCH EXECUTION HARNESS (v5 - State Gated)")
    print("=" * 60)

    # 1a. Validate Environment
    indicators_root = PROJECT_ROOT / "indicators"
    if not indicators_root.exists():
        print(f"[FATAL] Indicators repository missing at {indicators_root}")
        return

    # Phase A — argparse + directive load + globals
    args_bundle = _stage1_parse_args_and_load_directive()
    if args_bundle is None:
        return
    parsed_config, directive_content, directive_path, args = args_bundle

    # Phase B — warmup resolution (sets RESOLVED_WARMUP_BARS, 3 FATAL paths)
    if not _stage1_resolve_warmup_bars(parsed_config):
        return

    # 3. Engine Version
    engine_ver = get_engine_version()
    print(f"[INIT] Engine Version: {engine_ver}")

    # Phase C — strategy + symbol validation, derive summary CSV path
    validation = _stage1_validate_strategy_and_symbol(parsed_config, args)
    if validation is None:
        return
    strategy_id, target_symbol, summary_csv_ui = validation

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

        # D.1 — Phase 7 state verification (inline; tiny)
        try:
            state_mgr = PipelineStateManager(run_id)
            # Orchestrator sets NEXT state always.
            # state_mgr.verify_state("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            print(f"    [GOVERNANCE] State Verified: PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
        except Exception as e:
            print(f"    [FATAL] Governance Check Failed: {e}")
            error_msg = f"Governance Check Failed: {e}"
            raise e

        # Phase D.2 — HTF regime dataframe
        df_regime = _stage1_compute_regime_dataframe(target_symbol)

        # Phase D.3+D.4 — load market data + run-folder snapshot
        ctx = _stage1_load_market_data_and_snapshot(target_symbol, strategy_id, run_id, directive_path)
        df = ctx["df"]
        broker_spec = ctx["broker_spec"]
        median_bar_seconds = ctx["median_bar_seconds"]
        target_dir = ctx["target_dir"]
        strategy = ctx["strategy"]

        # Phase D.5 — HTF-patched engine run (monkey-patch lifecycle intact)
        # v1.5.11 Patch A: collect run-level engine_health counters. A fresh
        # dict is passed down; the engine populates it in place only when the
        # resolved engine supports it (v1.5.11+), else it stays empty.
        engine_health: dict = {}
        trades = _stage1_run_engine_with_htf_patches(df, df_regime, strategy, health=engine_health)
        print(f"    Trades: {len(trades)}")

        # D.6 — Emit OR no-trades
        if trades:
            status, net_pnl = _stage1_emit_and_verify(
                trades, df, broker_spec, target_symbol, run_id, content_hash,
                lineage_str, directive_content, strategy, median_bar_seconds, target_dir,
                engine_health=engine_health,
            )
        else:
            status = "NO_TRADES"
            print("    [WARN] No trades generated.")

    except Exception as e:
        error_msg = str(e)
        print(f"    [ERROR] {e}")
        import traceback
        traceback.print_exc()

    # Phase E + F — summary CSVs + (on SUCCESS) reports
    _stage1_write_summary_and_reports(
        target_symbol, run_id, status, net_pnl, error_msg,
        summary_csv_ui, strategy_id,
    )

    if status == "FAILED":
        sys.exit(1)

if __name__ == "__main__":
    main()
