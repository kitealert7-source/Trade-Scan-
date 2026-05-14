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
    behaviour. Returns a signal on the first `check_entry` call (signal
    sign = direction); returns None thereafter. `check_exit` always
    returns False so the engine never closes the position via signal —
    the recycle rule does that via direct BarState mutation.

    STRATEGY_SIGNATURE: declared explicitly to override the engine's
    default 2× ATR stop. Basket recycle rules own exit behaviour
    end-to-end; engine fallback stops would close positions before the
    rule's harvest target / floor can engage. Setting
    `atr_multiplier: 100000.0` makes the engine stop effectively
    unreachable (≈ 10,000 pips on 5m FX) — the recycle rule's safety
    caps (DD freeze 10%, margin freeze 15%, equity floor) provide the
    real risk control.
    """

    timeframe = "5m"

    # Marker for tools/basket_runner.py fast-path detection. ContinuousHold
    # only signals once (bar 1) and never asks the engine to evaluate
    # signals after, so BasketRunner can skip evaluate_bar entirely.
    # See Phase 5b.4b.
    _basket_fast_path = True

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "entry_logic":           {"type": "continuous_hold_first_bar"},
            "entry_when_flat_only":  True,
            "exit_logic":            {"type": "basket_rule_owned"},
            "pyramiding":            False,
            "reset_on_exit":         False,
            "stop_loss":             {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "take_profit":           {"enabled": False},
            "trailing_stop":         {"enabled": False},
        },
        "indicators": [],
        "order_placement":           {"type": "market", "execution_timing": "next_bar_open"},
        "position_management":       {"lots": 0.01},   # actual lot set on BasketLeg
        "signal_version":            1,
        "signature_version":         2,
        "trade_management":          {"direction": "basket_leg", "reentry": {"allowed": False}, "session_reset": "none"},
        "version":                   1,
    }
    # --- STRATEGY SIGNATURE END ---

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
        """No indicators required — pure time-based entry. The engine
        computes ATR internally when needed for its (now effectively
        disabled) stop fallback."""
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        if self._has_opened:
            return None
        self._has_opened = True
        return {"signal": int(self.direction)}

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False
