"""test_cointegration_meanrev_v1.py — C2 recycle rule tests.

Validates the COINTREV mean-reversion rule against synthetic basket legs
with controlled `intra_z` paths covering each exit condition. No
basket_data_loader / pipeline dependency — uses fixture legs constructed
in-test.

Tests cover:
  * param validation (ordering: exit_z < entry_z < stop_z)
  * BASKET_OPEN event fires when both legs open
  * REVERSION_EXIT triggers on |z| <= exit_z
  * STOP_LOSS triggers on |z| >= stop_z
  * TIME_STOP triggers on elapsed >= time_stop_bars
  * No pyramiding (recycle_count stays 0)
  * Legs cleanly reset (in_pos=False, lot=initial) after liquidation
  * No double-exit (rule short-circuits if already liquidated this cycle)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.recycle_rules.cointegration_meanrev_v1 import CointMeanRevV1Rule


# ---------------------------------------------------------------------------
# Lightweight stubs mirroring BasketLeg / BasketRunner public surface
# ---------------------------------------------------------------------------


@dataclass
class _LegState:
    in_pos: bool = False
    direction: int = 0
    entry_price: float = 0.0
    entry_index: int = 0
    pending_entry: Any = None


@dataclass
class _StubLeg:
    symbol: str
    direction: int            # +1 long, -1 short
    lot: float
    df: pd.DataFrame
    trades: list = field(default_factory=list)
    state: _LegState = field(default_factory=_LegState)


class _StubBasketRunner:
    """Minimal stand-in for BasketRunner — exposes only _initial_lots
    which the rule reads inside _liquidate."""
    def __init__(self, initial_lots: dict[str, float]):
        self._initial_lots = initial_lots


# ---------------------------------------------------------------------------
# Path builder — synthesize a leg df with deterministic z and price
# ---------------------------------------------------------------------------


def _build_leg_df(z_path: list[float],
                   close_path: list[float] | None = None,
                   qualified: bool = True) -> pd.DataFrame:
    """Make a leg.df indexed by 15m timestamps with intra_z and close."""
    n = len(z_path)
    ts = pd.date_range("2025-01-01", periods=n, freq="15min")
    if close_path is None:
        close_path = [1.0] * n
    return pd.DataFrame({
        "close": close_path,
        "intra_z": z_path,
        "qualified_daily": [qualified] * n,
    }, index=ts)


def _make_legs(z_path: list[float], *, initial_lot: float = 0.1):
    """Make two legs (A=long, B=short) sharing the same z-path on leg[0].

    For the rule we only need `close` (for PnL) and `intra_z` on legs[0].df
    (the rule reads intra_z from legs[0]). Equal-lot, both in_pos for
    cycle tests.
    """
    # Use simple price paths so leg_pnl_usd calcs return non-degenerate values
    # but exact PnL doesn't matter for these tests (we test EXIT TRIGGERING).
    n = len(z_path)
    a_close = list(np.linspace(1.0, 1.01, n))
    b_close = list(np.linspace(100.0, 100.5, n))
    leg_a = _StubLeg(
        symbol="EURUSD", direction=+1, lot=initial_lot,
        df=_build_leg_df(z_path, a_close),
    )
    leg_b = _StubLeg(
        symbol="USDJPY", direction=-1, lot=initial_lot,
        df=_build_leg_df(z_path, b_close),   # same z; rule reads legs[0].df
    )
    return [leg_a, leg_b]


def _open_basket(legs, *, entry_index: int, entry_z: float):
    """Helper: set both legs to in_pos at the chosen entry bar."""
    for leg in legs:
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_price = float(leg.df.iloc[entry_index]["close"])
        leg.state.entry_index = entry_index


def _make_rule(**overrides) -> CointMeanRevV1Rule:
    """Build a CointMeanRevV1Rule with sensible test defaults +
    minimal parent attributes the parquet-emit machinery reads."""
    defaults = dict(
        entry_z=2.0,
        exit_z=1.0,
        stop_z=4.0,
        time_stop_bars=192,
        initial_notional_usd=1000.0,
    )
    defaults.update(overrides)
    rule = CointMeanRevV1Rule(**defaults)
    rule.directive_id = "TEST_DIRECTIVE"
    rule.basket_id = "TEST_BASKET"
    rule.run_id = "TEST_RUN"
    return rule


def _wire_runner(rule, legs):
    rule.basket_runner = _StubBasketRunner(
        initial_lots={leg.symbol: leg.lot for leg in legs}
    )


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------


class TestParamValidation:

    def test_valid_params_construct_ok(self):
        rule = CointMeanRevV1Rule(entry_z=2.0, exit_z=1.0, stop_z=4.0)
        assert rule.entry_z == 2.0

    def test_exit_must_be_less_than_entry(self):
        with pytest.raises(ValueError, match="exit_z < entry_z"):
            CointMeanRevV1Rule(entry_z=1.0, exit_z=2.0, stop_z=4.0)

    def test_entry_must_be_less_than_stop(self):
        with pytest.raises(ValueError, match="entry_z < stop_z"):
            CointMeanRevV1Rule(entry_z=5.0, exit_z=1.0, stop_z=4.0)

    def test_time_stop_must_be_positive(self):
        with pytest.raises(ValueError, match="time_stop_bars must be > 0"):
            CointMeanRevV1Rule(time_stop_bars=0)

    def test_initial_notional_must_be_positive(self):
        with pytest.raises(ValueError, match="initial_notional_usd must be > 0"):
            CointMeanRevV1Rule(initial_notional_usd=-1.0)


# ---------------------------------------------------------------------------
# BASKET_OPEN detection
# ---------------------------------------------------------------------------


class TestBasketOpen:

    def test_open_event_fires_on_first_bar_both_legs_in_pos(self):
        # z stays at 2.5 (above entry, below stop) — no exit, only open event
        legs = _make_legs([2.5] * 10)
        _open_basket(legs, entry_index=2, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)

        # Apply rule for bar 2 onward; basket should open on bar 2
        for i in range(3, 6):
            rule.apply(legs, i, legs[0].df.index[i])

        opens = [e for e in rule.recycle_events if e["action"] == "BASKET_OPEN"]
        assert len(opens) == 1
        assert opens[0]["bar_index"] == 3
        # Recorded entry_z is from the bar where open detected (=bar 3 z value)
        assert opens[0]["entry_z"] == 2.5

    def test_no_open_event_when_legs_not_in_pos(self):
        legs = _make_legs([2.5] * 10)
        # legs.state.in_pos stays False
        rule = _make_rule()
        _wire_runner(rule, legs)
        for i in range(5):
            rule.apply(legs, i, legs[0].df.index[i])
        opens = [e for e in rule.recycle_events if e["action"] == "BASKET_OPEN"]
        assert len(opens) == 0


# ---------------------------------------------------------------------------
# Exit triggers
# ---------------------------------------------------------------------------


class TestReversionExit:

    def test_winner_exit_on_abs_z_below_exit_z(self):
        # z path: starts at 2.5 (entry already happened by stub), drops to 0.8
        # by bar 5 → REVERSION_EXIT should fire
        z = [2.5] * 5 + [0.8] * 5
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        for i in range(1, 10):
            rule.apply(legs, i, legs[0].df.index[i])
        liquidations = [e for e in rule.recycle_events if e["action"] == "LIQUIDATE"]
        assert len(liquidations) == 1
        assert liquidations[0]["reason"] == "REVERSION_EXIT"
        # Liquidation should happen at the first bar where |z| <= exit_z
        assert liquidations[0]["bar_index"] == 5
        # Counters
        assert rule._n_reversion_exits == 1
        assert rule._n_stop_exits == 0
        assert rule._n_time_exits == 0

    def test_negative_z_reversion_also_triggers(self):
        # z entered at -2.5, reverts to -0.5 → REVERSION_EXIT
        z = [-2.5] * 5 + [-0.5] * 5
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=-2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        for i in range(1, 10):
            rule.apply(legs, i, legs[0].df.index[i])
        liquidations = [e for e in rule.recycle_events if e["action"] == "LIQUIDATE"]
        assert len(liquidations) == 1
        assert liquidations[0]["reason"] == "REVERSION_EXIT"


class TestStopLoss:

    def test_stop_loss_on_abs_z_above_stop_z(self):
        # z worsens from 2.5 to 4.5 → STOP_LOSS
        z = [2.5, 3.0, 3.5, 4.5, 4.5, 4.5]
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        for i in range(1, len(z)):
            rule.apply(legs, i, legs[0].df.index[i])
        liquidations = [e for e in rule.recycle_events if e["action"] == "LIQUIDATE"]
        assert len(liquidations) == 1
        assert liquidations[0]["reason"] == "STOP_LOSS"
        assert liquidations[0]["bar_index"] == 3   # first bar where |z| >= 4
        assert rule._n_stop_exits == 1

    def test_stop_loss_negative_direction(self):
        # Entered short at z=2.5; spread blows out further: z goes to 5.0
        z = [2.5, 3.5, 5.0]
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        for i in range(1, len(z)):
            rule.apply(legs, i, legs[0].df.index[i])
        liquidations = [e for e in rule.recycle_events if e["action"] == "LIQUIDATE"]
        assert liquidations[0]["reason"] == "STOP_LOSS"


class TestTimeStop:

    def test_time_stop_after_window_elapses(self):
        # z stays at 2.5 forever (no other exit triggers).
        # entry_bar_idx is set lazily on the FIRST apply() call where
        # both legs are detected in_pos (=i=1 here). Time stop fires when
        # elapsed (i - entry_bar_idx) >= time_stop_bars → bar 1 + 5 = 6.
        z = [2.5] * 20
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule(time_stop_bars=5)
        _wire_runner(rule, legs)
        for i in range(1, len(z)):
            rule.apply(legs, i, legs[0].df.index[i])
        liquidations = [e for e in rule.recycle_events if e["action"] == "LIQUIDATE"]
        assert len(liquidations) == 1
        assert liquidations[0]["reason"] == "TIME_STOP"
        assert liquidations[0]["bar_index"] == 6
        assert rule._n_time_exits == 1


# ---------------------------------------------------------------------------
# Liquidation cleanup
# ---------------------------------------------------------------------------


class TestLiquidationCleanup:

    def test_legs_out_of_pos_after_liquidation(self):
        z = [2.5, 0.5]
        legs = _make_legs(z, initial_lot=0.1)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        rule.apply(legs, 1, legs[0].df.index[1])
        for leg in legs:
            assert not leg.state.in_pos
            assert leg.state.direction == 0
            assert leg.lot == 0.1   # reset to initial

    def test_no_double_exit_in_same_cycle(self):
        # After REVERSION_EXIT, next bar with stop-level z should NOT fire
        # another liquidation (because basket is no longer open)
        z = [2.5, 0.5, 5.0]
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        rule.apply(legs, 1, legs[0].df.index[1])   # REVERSION_EXIT
        rule.apply(legs, 2, legs[0].df.index[2])   # would-be STOP_LOSS — but legs are flat
        liquidations = [e for e in rule.recycle_events if e["action"] == "LIQUIDATE"]
        assert len(liquidations) == 1   # only one

    def test_recycle_count_stays_zero_no_pyramiding(self):
        # Even on a clean winning trade, rule never pyramids
        z = [2.5, 1.5, 1.0, 0.5]
        legs = _make_legs(z)
        _open_basket(legs, entry_index=0, entry_z=2.5)
        rule = _make_rule()
        _wire_runner(rule, legs)
        for i in range(1, len(z)):
            rule.apply(legs, i, legs[0].df.index[i])
        # No pyramid events
        pyramids = [e for e in rule.recycle_events if e["action"] == "PYRAMID"]
        assert len(pyramids) == 0
        # All per-bar records have recycle_count = 0
        for r in rule.per_bar_records:
            assert r["recycle_count"] == 0
