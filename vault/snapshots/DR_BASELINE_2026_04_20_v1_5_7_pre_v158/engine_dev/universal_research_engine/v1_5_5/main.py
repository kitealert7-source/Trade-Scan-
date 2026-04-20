"""
Universal_Research_Engine v1.2.0 — Main Entry Point
Pure orchestration. Strategy logic execution only.
Governed by: STRATEGY_PLUGIN_CONTRACT.md, SOP_TESTING, SOP_OUTPUT

This engine:
- Executes strategy logic via execution_loop
- Returns raw trade records
- Does NOT load data (caller provides data)
- Does NOT emit artifacts (caller handles emission)
- Does NOT parse CSVs or normalize timeframes
"""

import sys
import importlib
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Dynamic import with explicit boundary checks — fails at load time, not mid-session
import importlib.util
_loop_path = Path(__file__).parent / "execution_loop.py"
if not _loop_path.exists():
    raise ImportError(f"execution_loop.py not found at {_loop_path}")
spec = importlib.util.spec_from_file_location("execution_loop", _loop_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not build module spec for {_loop_path}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
if not callable(getattr(mod, "run_execution_loop", None)):
    raise ImportError(
        f"run_execution_loop not found or not callable in {_loop_path} — contract violation"
    )
run_execution_loop = mod.run_execution_loop

from engines.indicator_warmup_resolver import resolve_strategy_warmup, extract_indicators_from_strategy

ENGINE_NAME = "Universal_Research_Engine"
ENGINE_VERSION = "1.5.5"
__version__ = "1.5.5"


def load_strategy(strategy_id: str):
    """Dynamically load strategy plugin."""
    module_path = f"strategies.{strategy_id}.strategy"
    module = importlib.import_module(module_path)
    StrategyClass = getattr(module, "Strategy", None)
    if StrategyClass is None:
        raise ValueError(f"Strategy class not found in {module_path}")
    return StrategyClass()


def run_engine(df, strategy) -> List[dict]:
    """
    Execute strategy on provided data.
    
    Args:
        df: DataFrame with OHLCV market data (authoritative source determined by execution context)
        strategy: Strategy instance with prepare_indicators, check_entry, check_exit
        
    Returns:
        List of trade dictionaries with:
        - entry_timestamp
        - exit_timestamp
        - direction
        - entry_price
        - exit_price
        - bars_held
    """
    if df is None or df.empty:
        raise ValueError("No data provided to engine")
    
    # --- DYNAMIC WARM-UP CALCULATION ---
    # Resolve required warmup bars based on strategy indicators and registry metadata.
    indicator_list = extract_indicators_from_strategy(strategy)
    calculated_warmup = resolve_strategy_warmup(indicator_list)
    
    # Fallback to safety floor (e.g. 50 bars) if calculated warmup is suspiciously low
    # while ensuring it doesn't exceed 250 unless strictly required.
    warmup_bars = max(calculated_warmup, 50)
    
    available_history = len(df)
    evaluation_start_index = min(warmup_bars, available_history - 1)
    evaluation_start_index = max(0, evaluation_start_index)

    # Wrap strategy signals to "mute" them during warm-up period.
    # This enforces the safety gate without modifying the frozen execution loop.
    original_check_entry = strategy.check_entry
    original_check_exit = strategy.check_exit
    
    def wrapped_check_entry(ctx):
        if ctx.index < evaluation_start_index:
            return None
        return original_check_entry(ctx)
    
    def wrapped_check_exit(ctx):
        if ctx.index < evaluation_start_index:
            return None
        return original_check_exit(ctx)
    
    strategy.check_entry = wrapped_check_entry
    strategy.check_exit = wrapped_check_exit
    
    try:
        trades = run_execution_loop(df, strategy)
    finally:
        # Restore original methods to prevent side-effects if object is reused.
        strategy.check_entry = original_check_entry
        strategy.check_exit = original_check_exit
        
    return trades


# This module is designed to be imported, not run directly.
# The calling harness handles:
# - Preflight validation
# - Data loading
# - Artifact emission
