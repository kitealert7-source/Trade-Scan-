# =============================================================================
# Engine v1.5.9 — EXPERIMENTAL — execution loop (extraction shell).
#
# v1.5.9 is the v1.5.8 per-bar block lifted into a standalone callable
# (evaluate_bar()) so the same per-bar logic can be reused from a streaming
# live runtime without re-implementation.  This file is the batch driver:
#
#   prepare_indicators
#   apply_regime_model
#   resolve_engine_config              — was inline in v1.5.8 lines 215-256
#   for i in range(len(df)):
#       trade = evaluate_bar(...)      — was inline in v1.5.8 lines 263-644
#       if trade is not None:
#           trades.append(trade)
#   finalize_force_close               — was inline in v1.5.8 lines 646-694
#
# Logic, ordering, and arithmetic are unchanged from v1.5.8.
# Acceptance: byte-identical backtest output to v1.5.8.
# =============================================================================
"""
Universal Research Engine v1.5.9 — Execution Loop (EXPERIMENTAL).

Same contract as v1.5.8.  Per-bar logic is dispatched to evaluate_bar.py.
"""

from __future__ import annotations

import pandas as pd
from typing import Any

from engines.protocols import StrategyProtocol
from engines.regime_state_machine import apply_regime_model

from engine_dev.universal_research_engine.v1_5_9.evaluate_bar import (
    BarState,
    ContextView,
    EngineConfig,
    ENGINE_ATR_MULTIPLIER,
    evaluate_bar,
    finalize_force_close,
    resolve_engine_config,
    resolve_exit,
)

__all__ = [
    "ContextView",
    "resolve_exit",
    "run_execution_loop",
    "ENGINE_VERSION",
    "ENGINE_STATUS",
]

ENGINE_VERSION    = "1.5.9"
ENGINE_STATUS     = "EXPERIMENTAL"
ENGINE_FREEZE_DATE = None  # EXPERIMENTAL engines do not have a freeze date.


def run_execution_loop(df: pd.DataFrame, strategy: StrategyProtocol) -> list[dict[str, Any]]:
    """
    v1.5.9 execution loop. Strategy-agnostic.

    Identical contract to v1.5.8.  Per-bar logic delegated to evaluate_bar().
    """
    df = strategy.prepare_indicators(df)

    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df.index = pd.DatetimeIndex(df['timestamp'])
        elif 'time' in df.columns:
            df.index = pd.DatetimeIndex(df['time'])

    try:
        df = apply_regime_model(df)
    except Exception as e:
        raise RuntimeError(f"Engine Regime Implementation Failed: {e}") from e

    config = resolve_engine_config(strategy)
    state  = BarState()
    trades: list[dict[str, Any]] = []

    for i in range(len(df)):
        trade = evaluate_bar(df, i, state, strategy, config)
        if trade is not None:
            trades.append(trade)

    finalize_force_close(df, state, trades)

    return trades
