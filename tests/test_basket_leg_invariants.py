"""Invariant tests for BasketLeg direction-model.

These tests guard the architectural fix for the 2026-05-24 leg_direction_flip_bug
(see RESEARCH_MEMORY of that date and commits 92fb187 / e0a1d8c / the Option-B
follow-up). The invariant is:

  - `leg.direction` is YAML BASE only and MUST NOT be mutated post-init.
  - Cycle-aware code reads `leg.effective_direction` (which derives from
    `leg.state.direction` when in-position, else falls back to `leg.direction`).

If a future rule reverts to mutating `leg.direction` (the deprecated Option-A
workaround), the test `test_leg_direction_immutable_through_short_spread_cycle`
catches it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg
from tools.recycle_strategies import (
    PineZRevArmedState,
    PineZRevLegStrategy,
)


class _NoOpStrategy:
    name = "noop"
    timeframe = "1d"
    def prepare_indicators(self, df):
        return df
    def check_entry(self, ctx):
        return None
    def check_exit(self, ctx):
        return False


def _make_leg(direction: int) -> BasketLeg:
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {"open": [1.0]*3, "high": [1.0]*3, "low": [1.0]*3, "close": [1.0]*3},
        index=idx,
    )
    return BasketLeg("TESTSYM", lot=0.01, direction=direction, df=df,
                     strategy=_NoOpStrategy())


# ---------- effective_direction property semantics ----------------------------

def test_effective_direction_flat_falls_back_to_yaml_base():
    """When leg is not in-position, effective_direction returns leg.direction."""
    long_leg = _make_leg(+1)
    short_leg = _make_leg(-1)
    assert long_leg.state.in_pos is False
    assert long_leg.effective_direction == +1
    assert short_leg.effective_direction == -1


def test_effective_direction_in_pos_returns_state_direction():
    """When in_pos, effective_direction returns state.direction (cycle-aware)."""
    long_leg = _make_leg(+1)   # YAML BASE: long
    # Engine opens SHORT cycle: state.direction inverted vs leg.direction.
    long_leg.state.in_pos = True
    long_leg.state.direction = -1
    assert long_leg.effective_direction == -1, (
        "effective_direction must follow state.direction during cycle, "
        "not the YAML BASE leg.direction"
    )
    assert long_leg.direction == +1, "leg.direction must not mutate"


def test_effective_direction_in_pos_long_cycle_matches_base():
    """LONG cycle: state.direction == leg.direction → effective matches both."""
    long_leg = _make_leg(+1)
    long_leg.state.in_pos = True
    long_leg.state.direction = +1
    assert long_leg.effective_direction == +1
    assert long_leg.direction == +1


def test_effective_direction_state_direction_zero_falls_back():
    """Defensive: if state.direction is 0 (cleared post-exit) but in_pos
    somehow True, effective_direction falls back to YAML BASE. Should not
    happen in practice but the fallback prevents PnL math from blowing up."""
    leg = _make_leg(+1)
    leg.state.in_pos = True
    leg.state.direction = 0   # not in (-1, +1)
    assert leg.effective_direction == +1   # falls back to YAML BASE


# ---------- Regression guard: future workarounds must not mutate leg.direction --

def test_leg_direction_immutable_through_short_spread_cycle():
    """Run a SHORT_SPREAD cycle through a real rule (pine_ratio_zrev_v1) and
    assert leg.direction is never mutated by the rule's BASKET_OPEN handling.

    If a future PR reintroduces the Option-A workaround
    (`leg.direction = leg.state.direction` at BASKET_OPEN), this test fails
    immediately — pointing at the architectural regression.
    """
    from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule

    class _FakeRunner:
        def __init__(self, lots):
            self._initial_lots = dict(lots)

    # Build two legs with pre-attached pine_zrev_signal column
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    closes_a = np.linspace(1.10, 1.11, 10)
    closes_b = np.linspace(150.0, 151.0, 10)
    signal = np.zeros(10, dtype=int)
    signal[2] = -1   # SHORT_SPREAD signal
    r_bar = np.full(10, 0.00733)

    def _build_df(closes):
        return pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes,
             "pine_zrev_signal": signal, "pine_zrev_r_bar": r_bar},
            index=idx,
        )

    shared = PineZRevArmedState()
    leg_a = BasketLeg("EURUSD", lot=0.01, direction=+1, df=_build_df(closes_a),
                      strategy=PineZRevLegStrategy("EURUSD", +1, armed_state=shared))
    leg_b = BasketLeg("USDJPY", lot=0.01, direction=-1, df=_build_df(closes_b),
                      strategy=PineZRevLegStrategy("USDJPY", -1, armed_state=shared))
    for leg in (leg_a, leg_b):
        leg.state = BarState()

    rule = PineRatioZRevRule(
        n_window=10, z_entry=2.0, entry_mode="absolute",
        default_initial_lot=0.01, target_notional_per_leg_usd=10_000.0,
        shared_armed_state=shared,
        run_id="TEST", directive_id="TEST", basket_id="TEST",
    )
    rule.basket_runner = _FakeRunner({"EURUSD": 0.01, "USDJPY": 0.01})
    rule._z_r_attached = True

    initial_a, initial_b = leg_a.direction, leg_b.direction   # +1, -1

    # Walk through bars 0-4: proposal, approval, fire, engine open, BASKET_OPEN.
    from types import SimpleNamespace
    def _step_legs(bar_ts):
        for leg in (leg_a, leg_b):
            row = leg.df.loc[bar_ts]
            ctx = SimpleNamespace(row=row, get=lambda k, d=None: row.get(k, d))
            leg.strategy.check_entry(ctx)

    _step_legs(idx[2]); rule.apply([leg_a, leg_b], 2, idx[2])
    _step_legs(idx[3]); rule.apply([leg_a, leg_b], 3, idx[3])

    # Engine fill simulation (state.direction = sign-flipped vs leg.direction)
    for leg in (leg_a, leg_b):
        leg.state.in_pos = True
        leg.state.direction = -leg.direction
        leg.state.entry_index = 4
        leg.state.entry_price = float(leg.df.iloc[4]["close"])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    rule.apply([leg_a, leg_b], 4, idx[4])

    # The invariant: leg.direction MUST NOT have been mutated.
    assert leg_a.direction == initial_a, (
        f"leg_a.direction was mutated from {initial_a} to {leg_a.direction}. "
        f"This violates the post-Option-B invariant: leg.direction is YAML "
        f"BASE only and must never be mutated. If you needed cycle-aware "
        f"direction in your rule, read leg.effective_direction instead."
    )
    assert leg_b.direction == initial_b, (
        f"leg_b.direction was mutated from {initial_b} to {leg_b.direction}. "
        f"Same invariant violation as above."
    )
    # And cycle-aware accessor returns the correct (state-based) direction.
    assert leg_a.effective_direction == -1
    assert leg_b.effective_direction == +1
