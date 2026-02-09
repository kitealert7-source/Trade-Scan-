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

# Fixed dynamic import
import importlib.util
spec = importlib.util.spec_from_file_location("execution_loop", Path(__file__).parent / "execution_loop.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
run_execution_loop = mod.run_execution_loop

ENGINE_NAME = "Universal_Research_Engine"
ENGINE_VERSION = "1.2.0"
__version__ = ENGINE_VERSION


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
        df: DataFrame with OHLCV data (clean, pre-processed)
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
    
    trades = run_execution_loop(df, strategy)
    return trades


# This module is designed to be imported, not run directly.
# The calling harness handles:
# - Preflight validation
# - Data loading
# - Artifact emission
