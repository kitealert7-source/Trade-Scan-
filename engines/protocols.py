"""
Engine Protocol Definitions
Trade_Scan Research Pipeline

Formal Protocol classes for the two core engine interfaces:
  1. StrategyProtocol  — what the engine expects from every strategy.py
  2. ContextViewProtocol — what strategies expect from the context adapter

These are structural (duck-typed) Protocols — strategies do NOT need to
inherit from them. A class that implements the right methods/attributes
satisfies the Protocol automatically.

Usage:
  - Type checkers (mypy, pyright) enforce at lint time
  - Runtime checks via isinstance() enabled by runtime_checkable
  - FilterStack and execution_loop use these for validation
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd

__all__ = ["ContextViewProtocol", "StrategyProtocol"]


# ---------------------------------------------------------------------------
# ContextView Protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class ContextViewProtocol(Protocol):
    """Contract for the context object passed to check_entry / check_exit.

    Replaces the _ENGINE_PROTOCOL marker attribute with a type-system-enforced
    protocol. Any object implementing get() and require() satisfies this.
    """

    def get(self, key: str, default: Any = None) -> Any:
        """Return indicator/field value, or default if missing/NaN."""
        ...

    def require(self, key: str) -> Any:
        """Return indicator/field value, or raise RuntimeError if missing."""
        ...


# ---------------------------------------------------------------------------
# Strategy Protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class StrategyProtocol(Protocol):
    """Contract every strategy.py must satisfy to be engine-compatible.

    Derived from STRATEGY_PLUGIN_CONTRACT.md and runtime usage in
    execution_loop.py + strategy_loader.py.

    Mandatory attributes:
      name             — must equal the strategy_id declared in the directive
      timeframe        — must match the portfolio/directive timeframe

    Mandatory methods:
      prepare_indicators(df) — attach all indicators to the DataFrame
      check_entry(ctx)       — return signal dict or None
      check_exit(ctx)        — return True to exit, False to stay

    Optional (not in Protocol — checked via hasattr at call sites):
      STRATEGY_SIGNATURE: dict          — trade management, filter config
      filter_stack: FilterStack         — instantiated in __init__
      _schema_sample() -> dict          — canonical signal for smoke testing
    """

    name: str
    timeframe: str

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute and attach all indicators. Must return the modified DataFrame."""
        ...

    def check_entry(self, ctx: ContextViewProtocol) -> dict[str, Any] | None:
        """Evaluate entry conditions for the current bar.

        Returns:
            dict with mandatory key 'signal' (1=long, -1=short) and optional
            keys 'stop_price', 'tp_price', 'entry_reference_price', 'entry_reason'.
            None if no entry signal.
        """
        ...

    def check_exit(self, ctx: ContextViewProtocol) -> bool:
        """Evaluate exit conditions for the current bar.

        Returns:
            True to exit the active position, False to hold.
        """
        ...
