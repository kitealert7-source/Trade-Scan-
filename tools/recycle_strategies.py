"""recycle_strategies.py — Per-leg strategies for basket directives.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5c.

Phase 5c provides real per-leg strategies that open positions for the
basket's recycle rule to act on. The simplest (and the one H2 needs) is
`ContinuousHoldStrategy` — opens once on the first bar, holds the
position continuously, never signals an exit. The H2CompressionRecycleRule
handles close+reopen events.

Why this exists separately from the per-symbol `strategies/<id>/strategy.py`
directories: basket legs are infrastructure-owned (the basket recycle rule
defines the strategy), not research-stage. Putting the leg strategies
under `tools/` makes the ownership explicit and keeps them out of the
per-symbol governance flow (no namespace_gate, no idea_registry entry,
no SIGNATURE_HASH).
"""
from __future__ import annotations

from typing import Any

import pandas as pd


__all__ = ["ContinuousHoldStrategy"]


class ContinuousHoldStrategy:
    """Open once at the first available bar; hold continuously.

    Used by basket directives where the recycle rule defines all exit
    behaviour. Returns a long signal on the first `check_entry` call;
    returns None thereafter. `check_exit` always returns False so the
    engine never closes the position via signal — the recycle rule does
    that via direct BarState mutation.

    Direction comes from the BasketLeg; this strategy is symbol-agnostic
    and only needs to know whether to emit signal=+1 (long) or signal=-1
    (short) on its single entry.

    STRATEGY_SIGNATURE is intentionally absent — basket legs are not in
    the per-symbol governance flow, so no SIGNATURE_HASH is required.
    """

    timeframe = "5m"

    def __init__(self, symbol: str, direction: int = +1) -> None:
        if direction not in (+1, -1):
            raise ValueError(
                f"ContinuousHoldStrategy: direction must be +1 or -1, got {direction!r}."
            )
        self.symbol = symbol
        self.direction = direction
        self.name = f"continuous_hold_{symbol}"
        self._has_opened = False

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """No indicators required — pure time-based entry."""
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        if self._has_opened:
            return None
        self._has_opened = True
        return {"signal": int(self.direction)}

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False
