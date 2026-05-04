"""
Stage-0.75 -- Strategy Dry-Run Validator (Pure, Side-Effect Free)
Authority: Pipeline Robustness Hardening
Status: MANDATORY EXECUTION GATE

Purpose:
    Verify the strategy can execute without crashing on a small data sample.
    This is a structural health check only.

Rules:
    1. PURE: No side effects. No state mutation. No artifact writes.
    2. NO GATING ON SIGNAL COUNT: Zero signals is a warning, not a failure.
    3. FAIL ONLY ON EXCEPTIONS: If prepare_indicators or check_entry raises, fail.
    4. SAMPLE SIZE: First 1000 bars of first declared symbol.
"""

import sys
import types
import importlib
import importlib.util
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.directive_utils import load_directive_yaml, get_key_ci
from engine_dev.universal_research_engine.v1_5_6.execution_loop import ContextView
from engines.regime_state_machine import apply_regime_model


def validate_strategy_dryrun(directive_id: str, first_symbol: str, directive_path) -> bool:
    """
    Perform a pure dry-run of the strategy on a small data sample.
    
    Returns True if strategy can execute without crashing.
    Returns False (hard fail) only if an exception is raised.
    Zero signals = warning, not failure.
    """
    print(f"[DRYRUN] Starting Stage-0.75 Dry-Run Validation for {directive_id}...")
    
    # 1. Parse directive for data path construction
    try:
        d_conf = load_directive_yaml(directive_path)
    except Exception as e:
        print(f"[DRYRUN] FATAL: Failed to load directive: {e}")
        return False

    test_block = get_key_ci(d_conf, "test") or {}
    
    broker = (get_key_ci(test_block, "broker") or get_key_ci(d_conf, "broker") or "OctaFX").lower()
    timeframe = get_key_ci(test_block, "timeframe") or get_key_ci(d_conf, "timeframe") or "15m"
    strategy_name = get_key_ci(test_block, "strategy") or get_key_ci(d_conf, "strategy") or directive_id
    
    # Normalize broker name for path
    broker_folder = broker.capitalize()
    if broker_folder.lower() == "octafx":
        broker_folder = "OctaFx"
    
    # 2. Load small data sample (first 1000 bars)
    from config.path_authority import ANTI_GRAVITY_DATA_ROOT as _ANTI_GRAVITY
    data_root = _ANTI_GRAVITY / "MASTER_DATA" / f"{first_symbol}_{broker_folder}_MASTER" / "RESEARCH"
    
    pattern = f"{first_symbol}_{broker_folder}_{timeframe}_*_RESEARCH.csv"
    files = sorted(data_root.glob(pattern))
    
    if not files:
        print(f"[DRYRUN] WARNING: No data found for {first_symbol}. Skipping dry-run (data issue, not strategy issue).")
        return True
    
    try:
        df = pd.read_csv(files[0], comment='#')
        if 'time' in df.columns:
            df['timestamp'] = df['time']
        df['timestamp'] = pd.to_datetime(
            df['timestamp'],
            dayfirst=True,
            format='mixed',
            errors='coerce'
        )
        bad_ts = int(df['timestamp'].isna().sum())
        if bad_ts == len(df):
            print("[DRYRUN] WARNING: All sample timestamps failed parsing. Skipping dry-run.")
            return True
        if bad_ts > 0:
            # print(f"[DRYRUN] WARNING: Dropping {bad_ts} rows with unparseable timestamps.")
            df = df[df['timestamp'].notna()].copy()
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        df = df.head(1000).reset_index(drop=True)
    except Exception as e:
        print(f"[DRYRUN] WARNING: Failed to load sample data: {e}. Skipping dry-run.")
        return True
    
    print(f"[DRYRUN] Loaded {len(df)} sample bars for {first_symbol}")
    
    # 3. Import and instantiate strategy (in-memory only)
    strategy_path = PROJECT_ROOT / "strategies" / strategy_name / "strategy.py"
    if not strategy_path.exists():
        print(f"[DRYRUN] FATAL: Strategy file not found: {strategy_path}")
        return False
    
    try:
        spec = importlib.util.spec_from_file_location("strategy_module", str(strategy_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        strategy = mod.Strategy()
    except Exception as e:
        print(f"[DRYRUN] FATAL: Strategy instantiation failed: {e}")
        return False
    
    print(f"[DRYRUN] Strategy instantiated: {strategy_name}")
    
    # 4. Run prepare_indicators
    try:
        df = strategy.prepare_indicators(df)
    except Exception as e:
        print(f"[DRYRUN] FATAL: prepare_indicators() raised exception: {e}")
        return False
    
    print(f"[DRYRUN] prepare_indicators() executed successfully")

    # 4b. Apply engine regime model (same as execution loop)
    try:
        df = apply_regime_model(df)
    except Exception as e:
        print(f"[DRYRUN] WARNING: apply_regime_model() failed: {e}. Continuing without engine fields.")

    # 5. Iterate check_entry over sample (pure -- no state mutation)
    signal_count = 0
    try:
        for i in range(len(df)):
            row = df.iloc[i]
            ns = types.SimpleNamespace(
                row=row,
                index=i,
                direction=0,
                trend_regime=row.get('trend_regime', None),
                volatility_regime=row.get('volatility_regime', None),
                trend_score=row.get('trend_score', None),
                trend_label=row.get('trend_label', None),
                entry_index=None,
                bars_held=0,
            )
            ctx = ContextView(ns)
            result = strategy.check_entry(ctx)
            if result is not None:
                signal_count += 1
    except Exception as e:
        print(f"[DRYRUN] FATAL: check_entry() raised exception on bar {i}: {e}")
        return False
    
    # 6. Report (zero signals = warning only, never a failure)
    if signal_count == 0:
        print(f"[DRYRUN] WARNING: 0 entry signals on {len(df)} sample bars.")
    else:
        print(f"[DRYRUN] {signal_count} entry signal(s) detected on {len(df)} sample bars.")
    
    print(f"[DRYRUN] Stage-0.75 PASSED (no exceptions)\\n")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/strategy_dryrun_validator.py <DIRECTIVE_ID>")
        sys.exit(1)
    
    d_id = sys.argv[1]
    if d_id.endswith(".txt"):
        d_path = Path(d_id)
        if not d_path.is_absolute():
             d_path = PROJECT_ROOT / "backtest_directives" / "active" / d_id
        d_id = d_path.stem
    else:
        d_path = PROJECT_ROOT / "backtest_directives" / "active" / f"{d_id}.txt"
    
    if not d_path.exists():
        print(f"[DRYRUN] FATAL: Directive not found: {d_path}")
        sys.exit(1)

    # Extract first symbol from directive
    try:
        data = load_directive_yaml(d_path)
        first_sym = data.get('symbols', ['XAUUSD'])[0]
    except Exception as e:
        print(f"[DRYRUN] WARNING: Could not parse directive symbols: {e}")
        first_sym = 'XAUUSD'

    success = validate_strategy_dryrun(d_id, first_sym, d_path)
    sys.exit(0 if success else 1)
