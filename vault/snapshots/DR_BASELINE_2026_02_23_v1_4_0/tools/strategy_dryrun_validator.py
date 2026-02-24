"""
Stage-0.75 — Strategy Dry-Run Validator (Pure, Side-Effect Free)
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


def validate_strategy_dryrun(directive_id: str, first_symbol: str, directive_path) -> bool:
    """
    Perform a pure dry-run of the strategy on a small data sample.
    
    Returns True if strategy can execute without crashing.
    Returns False (hard fail) only if an exception is raised.
    Zero signals = warning, not failure.
    """
    print(f"[DRYRUN] Starting Stage-0.75 Dry-Run Validation...")
    
    # 1. Parse directive for data path construction
    d_conf = load_directive_yaml(directive_path)
    test_block = get_key_ci(d_conf, "test") or {}
    
    broker = (get_key_ci(test_block, "broker") or get_key_ci(d_conf, "broker") or "OctaFX").lower()
    timeframe = get_key_ci(test_block, "timeframe") or get_key_ci(d_conf, "timeframe") or "15m"
    strategy_name = get_key_ci(test_block, "strategy") or get_key_ci(d_conf, "strategy") or directive_id
    
    # Normalize broker name for path
    broker_folder = broker.capitalize()
    if broker_folder.lower() == "octafx":
        broker_folder = "OctaFx"
    
    # 2. Load small data sample (first 1000 bars)
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / f"{first_symbol}_{broker_folder}_MASTER" / "RESEARCH"
    
    pattern = f"{first_symbol}_{broker_folder}_{timeframe}_*_RESEARCH.csv"
    files = sorted(data_root.glob(pattern))
    
    if not files:
        print(f"[DRYRUN] WARNING: No data found for {first_symbol}. Skipping dry-run (data issue, not strategy issue).")
        return True
    
    try:
        df = pd.read_csv(files[0], comment='#')
        if 'time' in df.columns:
            df['timestamp'] = df['time']
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
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
    
    # 5. Iterate check_entry over sample (pure — no state mutation)
    signal_count = 0
    try:
        for i in range(len(df)):
            row = df.iloc[i]
            ctx = types.SimpleNamespace(
                row=row,
                index=i,
                direction=0,
                trend_regime=row.get('trend_regime', 0),
                volatility_regime=row.get('volatility_regime', 0),
                entry_index=None,
                bars_held=0,
            )
            result = strategy.check_entry(ctx)
            if result is not None:
                signal_count += 1
    except Exception as e:
        print(f"[DRYRUN] FATAL: check_entry() raised exception on bar {i}: {e}")
        return False
    
    # 6. Report (zero signals = warning only, never a failure)
    if signal_count == 0:
        print(f"[DRYRUN] WARNING: 0 entry signals on {len(df)} sample bars. Strategy may have rare signals or may need review.")
    else:
        print(f"[DRYRUN] {signal_count} entry signal(s) detected on {len(df)} sample bars.")
    
    print(f"[DRYRUN] Stage-0.75 PASSED (no exceptions)")
    return True
