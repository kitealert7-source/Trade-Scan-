"""Tests for BasketRunner.soft_reset_basket primitive (Phase B, 2026-05-16).

The soft-reset primitive supports cyclical basket strategies (e.g.
H2_recycle@4 bump-and-liquidate) that need to close current sub-basket
positions and reopen fresh ones mid-window. Distinct from a true basket
exit — basket lifecycle continues.

Test scope:
  1. Initial-lot capture at __init__ — `_initial_lots` correctly records
     each leg's starting lot.
  2. Back-reference injection — `rule.basket_runner` set on every rule
     attached at __init__.
  3. soft_reset_basket resets lot, entry_price, entry_index, trade_high,
     trade_low per leg.
  4. soft_reset_basket keeps `leg.state.in_pos = True` (basket continues).
  5. soft_reset_basket validates `at_prices` — raises ValueError on
     missing symbol or non-positive price.
  6. soft_reset_basket does NOT mutate `_initial_lots` — even after a
     recycle has grown `leg.lot`, soft_reset restores the original.
  7. soft_reset_basket can be called multiple times within a basket (a
     cyclical strategy fires it once per liquidation event).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg, BasketRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _NoOpStrategy:
    """Minimal strategy — same shape used elsewhere in basket_runner tests."""
    name = "noop_soft_reset_fixture"
    timeframe = "5m"

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


def _ohlc(symbol: str, n: int = 60, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-09-02 00:00:00", periods=n, freq="5min", tz=None)
    base = 1.0 + np.cumsum(rng.normal(0.0, 0.0005, n))
    df = pd.DataFrame(
        {"open": base, "high": base + 0.0001, "low": base - 0.0001,
         "close": base, "volume": 1000.0},
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def _make_runner(leg_lots: dict[str, float] | None = None,
                 rules=None) -> BasketRunner:
    leg_lots = leg_lots or {"EURUSD": 0.01, "USDJPY": 0.01}
    legs = [
        BasketLeg(symbol=s, lot=l, direction=+1, df=_ohlc(s, seed=hash(s) & 0xFFFF),
                  strategy=_NoOpStrategy())
        for s, l in leg_lots.items()
    ]
    return BasketRunner(legs, rules=rules)


def _put_leg_in_position(leg: BasketLeg, entry_price: float, entry_index: int = 1) -> None:
    """Helper — simulate a leg being mid-trade so soft-reset semantics are testable."""
    leg.state = BarState()
    leg.state.in_pos = True
    leg.state.direction = leg.direction
    leg.state.entry_index = entry_index
    leg.state.entry_price = entry_price
    leg.state.trade_high = entry_price + 0.005
    leg.state.trade_low = entry_price - 0.003
    leg.state.entry_market_state = {
        "initial_stop_price": entry_price,
        "fill_bar_idx": entry_index,
        "signal_bar_idx": entry_index - 1,
    }


# ---------------------------------------------------------------------------
# 1. Initial-lot capture
# ---------------------------------------------------------------------------


def test_initial_lots_captured_at_init():
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.02})
    assert runner._initial_lots == {"EURUSD": 0.01, "USDJPY": 0.02}


def test_initial_lots_independent_of_subsequent_lot_mutation():
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.01})
    # Simulate a recycle add that grew the loser
    runner.legs[1].lot = 0.05
    assert runner._initial_lots["USDJPY"] == 0.01, (
        "Mutating leg.lot post-init must not change _initial_lots."
    )


# ---------------------------------------------------------------------------
# 2. Back-reference injection
# ---------------------------------------------------------------------------


class _RuleNeedingRunnerRef:
    """Models a rule that needs basket_runner access (e.g. H2_recycle@4)."""
    name = "rule_needing_ref"
    basket_runner = None

    def apply(self, legs, i, bar_ts):
        pass


class _RuleIgnoringRunnerRef:
    """Models a rule that doesn't care about basket_runner access."""
    name = "rule_ignoring_ref"

    def apply(self, legs, i, bar_ts):
        pass


def test_back_reference_injected_on_rule_that_declares_attribute():
    rule = _RuleNeedingRunnerRef()
    runner = _make_runner(rules=[rule])
    assert rule.basket_runner is runner


def test_back_reference_set_unconditionally_on_legacy_rule():
    # Legacy rules don't declare basket_runner — runner still sets it.
    # If the rule never reads the attribute this is a harmless no-op.
    rule = _RuleIgnoringRunnerRef()
    runner = _make_runner(rules=[rule])
    assert getattr(rule, "basket_runner", None) is runner


def test_back_reference_injected_on_each_rule_when_multiple():
    r1 = _RuleNeedingRunnerRef()
    r2 = _RuleNeedingRunnerRef()
    runner = _make_runner(rules=[r1, r2])
    assert r1.basket_runner is runner
    assert r2.basket_runner is runner


# ---------------------------------------------------------------------------
# 3. soft_reset_basket resets per-leg state
# ---------------------------------------------------------------------------


def test_soft_reset_restores_lot_to_initial():
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.01})
    # Simulate a recycle that grew both legs
    runner.legs[0].lot = 0.07
    runner.legs[1].lot = 0.06
    _put_leg_in_position(runner.legs[0], 1.10)
    _put_leg_in_position(runner.legs[1], 150.0)

    runner.soft_reset_basket(
        at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].lot == 0.01
    assert runner.legs[1].lot == 0.01


def test_soft_reset_resets_entry_price_to_at_prices():
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.01})
    _put_leg_in_position(runner.legs[0], entry_price=1.10)
    _put_leg_in_position(runner.legs[1], entry_price=150.0)

    runner.soft_reset_basket(
        at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].state.entry_price == 1.105
    assert runner.legs[1].state.entry_price == 151.0


def test_soft_reset_resets_entry_index():
    runner = _make_runner()
    _put_leg_in_position(runner.legs[0], entry_price=1.10, entry_index=1)
    _put_leg_in_position(runner.legs[1], entry_price=150.0, entry_index=1)

    runner.soft_reset_basket(
        at_index=42, at_ts=pd.Timestamp("2024-09-02 03:30:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].state.entry_index == 42
    assert runner.legs[1].state.entry_index == 42


def test_soft_reset_resets_trade_high_low_to_current_price():
    runner = _make_runner()
    _put_leg_in_position(runner.legs[0], entry_price=1.10)
    # Manually drift trade_high / trade_low away from entry — simulate
    # in-trade tracking up to the reset bar.
    runner.legs[0].state.trade_high = 1.15
    runner.legs[0].state.trade_low = 1.08
    _put_leg_in_position(runner.legs[1], entry_price=150.0)
    runner.legs[1].state.trade_high = 155.0
    runner.legs[1].state.trade_low = 148.0

    runner.soft_reset_basket(
        at_index=20, at_ts=pd.Timestamp("2024-09-02 01:40:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].state.trade_high == 1.105
    assert runner.legs[0].state.trade_low == 1.105
    assert runner.legs[1].state.trade_high == 151.0
    assert runner.legs[1].state.trade_low == 151.0


# ---------------------------------------------------------------------------
# 4. soft_reset_basket keeps in_pos=True (basket continues)
# ---------------------------------------------------------------------------


def test_soft_reset_keeps_in_pos_true():
    runner = _make_runner()
    _put_leg_in_position(runner.legs[0], entry_price=1.10)
    _put_leg_in_position(runner.legs[1], entry_price=150.0)
    assert runner.legs[0].state.in_pos
    assert runner.legs[1].state.in_pos

    runner.soft_reset_basket(
        at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].state.in_pos
    assert runner.legs[1].state.in_pos


def test_soft_reset_preserves_entry_market_state():
    """engine internals must survive (finalize_force_close reads these)."""
    runner = _make_runner()
    _put_leg_in_position(runner.legs[0], entry_price=1.10)
    original_ems = dict(runner.legs[0].state.entry_market_state)
    runner.soft_reset_basket(
        at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].state.entry_market_state == original_ems


# ---------------------------------------------------------------------------
# 5. Input validation
# ---------------------------------------------------------------------------


def test_soft_reset_raises_when_at_prices_missing_symbol():
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.01})
    _put_leg_in_position(runner.legs[0], 1.10)
    _put_leg_in_position(runner.legs[1], 150.0)

    with pytest.raises(ValueError, match="USDJPY"):
        runner.soft_reset_basket(
            at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
            at_prices={"EURUSD": 1.105},  # missing USDJPY
        )


def test_soft_reset_raises_on_non_positive_price():
    runner = _make_runner()
    _put_leg_in_position(runner.legs[0], 1.10)
    _put_leg_in_position(runner.legs[1], 150.0)

    with pytest.raises(ValueError, match="positive"):
        runner.soft_reset_basket(
            at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
            at_prices={"EURUSD": 1.105, "USDJPY": -1.0},
        )


def test_soft_reset_raises_on_zero_price():
    runner = _make_runner()
    _put_leg_in_position(runner.legs[0], 1.10)
    _put_leg_in_position(runner.legs[1], 150.0)

    with pytest.raises(ValueError, match="positive"):
        runner.soft_reset_basket(
            at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
            at_prices={"EURUSD": 1.105, "USDJPY": 0.0},
        )


# ---------------------------------------------------------------------------
# 6. _initial_lots invariant
# ---------------------------------------------------------------------------


def test_soft_reset_does_not_mutate_initial_lots():
    """Calling soft_reset must not change the captured _initial_lots dict."""
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.02})
    snapshot = dict(runner._initial_lots)
    _put_leg_in_position(runner.legs[0], 1.10)
    _put_leg_in_position(runner.legs[1], 150.0)
    runner.legs[0].lot = 0.07  # post-recycle growth

    runner.soft_reset_basket(
        at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner._initial_lots == snapshot


# ---------------------------------------------------------------------------
# 7. Multiple soft_reset calls (cyclical use)
# ---------------------------------------------------------------------------


def test_soft_reset_can_fire_multiple_times():
    """Cyclical strategies call soft_reset once per liquidation event;
    each call must restore to initial_lot regardless of prior cycles."""
    runner = _make_runner({"EURUSD": 0.01, "USDJPY": 0.01})
    _put_leg_in_position(runner.legs[0], 1.10)
    _put_leg_in_position(runner.legs[1], 150.0)

    # Cycle 1: simulate recycle adds, then reset
    runner.legs[0].lot = 0.07
    runner.legs[1].lot = 0.05
    runner.soft_reset_basket(
        at_index=10, at_ts=pd.Timestamp("2024-09-02 00:50:00"),
        at_prices={"EURUSD": 1.105, "USDJPY": 151.0},
    )
    assert runner.legs[0].lot == 0.01
    assert runner.legs[1].lot == 0.01

    # Cycle 2: simulate more recycle adds, then reset again
    runner.legs[0].lot = 0.04
    runner.legs[1].lot = 0.08
    runner.soft_reset_basket(
        at_index=30, at_ts=pd.Timestamp("2024-09-02 02:30:00"),
        at_prices={"EURUSD": 1.108, "USDJPY": 152.0},
    )
    assert runner.legs[0].lot == 0.01
    assert runner.legs[1].lot == 0.01
    assert runner.legs[0].state.entry_price == 1.108
    assert runner.legs[1].state.entry_price == 152.0
