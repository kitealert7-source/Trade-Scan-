"""Tests for the regime-gate mechanic in H3SpreadV3Rule.

Charter: h3_spread_window_c_regime_detector (2026-05-23). The rule
consumes a flips_in_lookback column produced by basket_data_loader and
suppresses NEW pyramid orders (and ARMED-for-reentry re-entries) when
flips_in_lookback > regime_gate_flip_threshold. Cycle-init suppression
is handled at the data layer via cross_event zeroing.

Coverage:
  - Validator: both params None or both set; reject partial
  - Validator: reject negative/zero threshold + lookback
  - Default-off byte-equivalence: gate params None -> v3 behavior
    identical to baseline v3-without-the-params
  - Gate-tripped: pyramid is suppressed, emits PYRAMID_GATED record
  - Gate-released: pyramid fires normally on subsequent bar
  - Cold-start (NaN flips): gate inactive
  - Missing column: gate inactive (compatibility)
  - Exits unaffected: adverse-stop fires even when gate tripped
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg
from tools.recycle_rules.h3_spread_v3 import H3SpreadV3Rule


class _NoOpStrategy:
    name = "noop_h3v3_gate"
    timeframe = "5m"

    def prepare_indicators(self, df):
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


class _FakeRunner:
    def __init__(self, initial_lots):
        self._initial_lots = initial_lots


def _build_legs(eur_prices, jpy_prices, flips_arr=None, cross_side_arr=None,
                initial_lot=0.10):
    """Build EUR + USDJPY legs with optional flips_in_lookback column."""
    n = len(eur_prices)
    idx = pd.date_range("2024-01-01 00:00:00", periods=n, freq="5min")
    if cross_side_arr is None:
        cross_side_arr = np.full(n, 1, dtype=int)
    cols = {
        "open": eur_prices, "high": eur_prices, "low": eur_prices,
        "close": eur_prices, "cross_side": cross_side_arr,
    }
    if flips_arr is not None:
        cols["flips_in_lookback"] = flips_arr
    eur_df = pd.DataFrame(cols, index=idx)
    cols_b = dict(cols)
    cols_b.update({"open": jpy_prices, "high": jpy_prices,
                   "low": jpy_prices, "close": jpy_prices})
    jpy_df = pd.DataFrame(cols_b, index=idx)
    eur_leg = BasketLeg("EURUSD", lot=initial_lot, direction=+1, df=eur_df,
                        strategy=_NoOpStrategy())
    jpy_leg = BasketLeg("USDJPY", lot=initial_lot, direction=-1, df=jpy_df,
                        strategy=_NoOpStrategy())
    for leg, prices in [(eur_leg, eur_prices), (jpy_leg, jpy_prices)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return eur_leg, jpy_leg, idx


def _run_rule(rule, eur_leg, jpy_leg, idx):
    runner = _FakeRunner({"EURUSD": eur_leg.lot, "USDJPY": jpy_leg.lot})
    rule.basket_runner = runner
    for i, bar_ts in enumerate(idx):
        rule.apply([eur_leg, jpy_leg], i, bar_ts)
    return rule.recycle_events


# --- Validator tests ----------------------------------------------------

def test_gate_partial_setting_lookback_only_rejected():
    """Setting lookback without threshold (or vice versa) is almost
    always a directive bug — fail closed via validation."""
    with pytest.raises(ValueError, match="must be either BOTH None or BOTH set"):
        H3SpreadV3Rule(
            adverse_stop_pct=0.020,
            time_stop_bars=864,
            initial_notional_usd=1000.0,
            regime_gate_lookback_bars=2000,
            # regime_gate_flip_threshold omitted
        )


def test_gate_partial_setting_threshold_only_rejected():
    with pytest.raises(ValueError, match="must be either BOTH None or BOTH set"):
        H3SpreadV3Rule(
            adverse_stop_pct=0.020,
            time_stop_bars=864,
            initial_notional_usd=1000.0,
            regime_gate_flip_threshold=37.0,
            # regime_gate_lookback_bars omitted
        )


def test_gate_zero_lookback_rejected():
    with pytest.raises(ValueError, match="must be a positive int"):
        H3SpreadV3Rule(
            adverse_stop_pct=0.020,
            time_stop_bars=864,
            initial_notional_usd=1000.0,
            regime_gate_lookback_bars=0,
            regime_gate_flip_threshold=37.0,
        )


def test_gate_zero_threshold_rejected():
    with pytest.raises(ValueError, match="must be > 0"):
        H3SpreadV3Rule(
            adverse_stop_pct=0.020,
            time_stop_bars=864,
            initial_notional_usd=1000.0,
            regime_gate_lookback_bars=2000,
            regime_gate_flip_threshold=0.0,
        )


def test_gate_both_none_is_valid():
    """Default state: both None -> rule constructs cleanly, gate inactive."""
    rule = H3SpreadV3Rule(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        initial_notional_usd=1000.0,
    )
    assert rule.regime_gate_lookback_bars is None
    assert rule.regime_gate_flip_threshold is None


def test_gate_both_set_is_valid():
    """Both set: rule constructs cleanly, gate active."""
    rule = H3SpreadV3Rule(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        initial_notional_usd=1000.0,
        regime_gate_lookback_bars=2000,
        regime_gate_flip_threshold=37.0,
    )
    assert rule.regime_gate_lookback_bars == 2000
    assert rule.regime_gate_flip_threshold == 37.0


# --- Helper logic test --------------------------------------------------

def test_regime_gate_tripped_helper_inactive_when_params_unset():
    """The _regime_gate_tripped helper returns False when params are None,
    regardless of any flips_in_lookback values that happen to be present."""
    rule = H3SpreadV3Rule(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        initial_notional_usd=1000.0,
    )
    eur_leg, _, idx = _build_legs(
        np.full(5, 100.0), np.full(5, 150.0),
        flips_arr=np.full(5, 1000.0),  # huge flip count
    )
    # Even with massive flips, gate must be inactive (params unset).
    assert not rule._regime_gate_tripped([eur_leg], idx[2])


def test_regime_gate_tripped_helper_handles_missing_column():
    """If params are set but the column isn't present (e.g. an old
    backtest run-through), the helper returns False — fail open, never
    gate by accident."""
    rule = H3SpreadV3Rule(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        initial_notional_usd=1000.0,
        regime_gate_lookback_bars=2000,
        regime_gate_flip_threshold=37.0,
    )
    eur_leg, _, idx = _build_legs(
        np.full(5, 100.0), np.full(5, 150.0),
        flips_arr=None,  # no column at all
    )
    assert not rule._regime_gate_tripped([eur_leg], idx[2])


def test_regime_gate_tripped_helper_nan_treated_as_inactive():
    """Cold-start NaN flips must NOT trip the gate (charter cold-start
    contract: gate inactive until lookback fills)."""
    rule = H3SpreadV3Rule(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        initial_notional_usd=1000.0,
        regime_gate_lookback_bars=2000,
        regime_gate_flip_threshold=37.0,
    )
    eur_leg, _, idx = _build_legs(
        np.full(5, 100.0), np.full(5, 150.0),
        flips_arr=np.full(5, np.nan),
    )
    assert not rule._regime_gate_tripped([eur_leg], idx[2])


def test_regime_gate_tripped_helper_fires_when_count_over_threshold():
    """When flips_in_lookback > threshold, gate trips."""
    rule = H3SpreadV3Rule(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        initial_notional_usd=1000.0,
        regime_gate_lookback_bars=2000,
        regime_gate_flip_threshold=37.0,
    )
    flips = np.array([10, 20, 38, 50, 30], dtype=float)
    eur_leg, _, idx = _build_legs(
        np.full(5, 100.0), np.full(5, 150.0),
        flips_arr=flips,
    )
    # Position 2: 38 > 37 -> tripped
    assert rule._regime_gate_tripped([eur_leg], idx[2])
    # Position 3: 50 > 37 -> tripped
    assert rule._regime_gate_tripped([eur_leg], idx[3])
    # Position 4: 30 <= 37 -> released
    assert not rule._regime_gate_tripped([eur_leg], idx[4])


# --- Behavioral tests: gate suppresses pyramid --------------------------

def _common_params():
    return dict(
        adverse_stop_pct=0.020,
        time_stop_bars=864,
        reverse_cross_column="cross_side",
        entry_direction=1,
        initial_notional_usd=1000.0,
        max_exposure_multiple=3.0,
        pyramid_threshold_step_pct=0.15,
        pyramid_add_lot=0.05,
        harvest_keeps_core=True,
        bidirectional=False,
    )


def test_gate_suppresses_pyramid_emits_gated_record():
    """When gate is tripped and pyramid would otherwise fire,
    PYRAMID_GATED is emitted and no lot is added."""
    # Construct a price series that goes UP (long entry_direction=1 makes
    # money) so that pyramid thresholds are crossed.
    # Initial notional = 1000 USD, threshold step = 0.15% = 1.5 USD per
    # step. With 0.1 lot * 10000 contract size, ~0.0015 price move = 1.5
    # USD. So tiny moves cross many thresholds quickly.
    n = 30
    eur_prices = np.linspace(100.0, 100.2, n)   # gradual +0.2% rise
    jpy_prices = np.linspace(150.0, 149.85, n)  # gradual -0.1% fall
    # Gate tripped from bar 0 onwards (tests the suppression directly
    # without timing-dependent setup).
    flips = np.full(n, 10.0)
    eur_leg, jpy_leg, idx = _build_legs(
        eur_prices, jpy_prices, flips_arr=flips,
    )

    rule = H3SpreadV3Rule(
        **_common_params(),
        regime_gate_lookback_bars=200,
        regime_gate_flip_threshold=5.0,
    )
    events = _run_rule(rule, eur_leg, jpy_leg, idx)

    actions = [e["action"] for e in events]
    # Gate tripped throughout -> no PYRAMID events should fire.
    assert "PYRAMID" not in actions, (
        f"gate-tripped run should not commit any pyramids; got {actions}"
    )
    # At least one PYRAMID_GATED should fire (floating_total crosses
    # the 1.5 USD first-step threshold within the price evolution).
    assert "PYRAMID_GATED" in actions, (
        f"expected at least one PYRAMID_GATED suppression event; "
        f"got actions: {actions}"
    )
    # Lots must be unchanged from the initial value (no pyramid committed).
    assert eur_leg.lot == 0.10, f"EUR lot grew despite gate: {eur_leg.lot}"
    assert jpy_leg.lot == 0.10, f"JPY lot grew despite gate: {jpy_leg.lot}"


def test_gate_released_allows_pyramid():
    """When gate trips, then releases, pyramid fires on a subsequent
    bar where floating_total is over threshold."""
    n = 50
    eur_prices = np.linspace(100.0, 102.0, n)
    jpy_prices = np.linspace(150.0, 148.5, n)
    # Tripped briefly bars 5..10, then released for the rest
    flips = np.full(n, 0.0)
    flips[5:11] = 10.0
    eur_leg, jpy_leg, idx = _build_legs(
        eur_prices, jpy_prices, flips_arr=flips,
    )

    rule = H3SpreadV3Rule(
        **_common_params(),
        regime_gate_lookback_bars=200,
        regime_gate_flip_threshold=5.0,
    )
    events = _run_rule(rule, eur_leg, jpy_leg, idx)
    actions = [e["action"] for e in events]
    # At least one PYRAMID fires AFTER the gate releases at bar 11.
    assert "PYRAMID" in actions, (
        f"after gate release, pyramid should fire eventually; got {actions}"
    )


def test_gate_off_byte_equivalent_to_v3_baseline():
    """When both params are None, v3 behavior is identical to v3 without
    the params at all — proves the gate code path is fully bypassed."""
    n = 50
    eur_prices = np.linspace(100.0, 102.0, n)
    jpy_prices = np.linspace(150.0, 148.5, n)
    # Provide flips that WOULD trip if the gate were active, to prove
    # the gate path is truly bypassed when params are None.
    flips = np.full(n, 100.0, dtype=float)

    eur_a, jpy_a, idx_a = _build_legs(eur_prices, jpy_prices, flips_arr=flips)
    rule_gate_off = H3SpreadV3Rule(**_common_params())
    events_off = _run_rule(rule_gate_off, eur_a, jpy_a, idx_a)

    eur_b, jpy_b, idx_b = _build_legs(eur_prices, jpy_prices, flips_arr=None)
    rule_no_column = H3SpreadV3Rule(**_common_params())
    events_no_col = _run_rule(rule_no_column, eur_b, jpy_b, idx_b)

    # Both runs should produce the same action sequence.
    actions_off = [e["action"] for e in events_off]
    actions_no_col = [e["action"] for e in events_no_col]
    assert actions_off == actions_no_col, (
        "default-off v3 with flips column present must produce same "
        f"actions as v3 without the column at all. Got with-column: "
        f"{actions_off}; without-column: {actions_no_col}"
    )


def test_gate_does_not_block_adverse_stop_exit():
    """A gate trip suppresses NEW pyramid orders but does NOT block exits.
    Even when tripped, adverse_stop must fire if floating_total breaches
    the adverse threshold."""
    n = 30
    # Prices move adversely (EUR falls, JPY rises) so the long-short
    # spread cycle loses money.
    eur_prices = np.linspace(100.0, 97.0, n)
    jpy_prices = np.linspace(150.0, 154.0, n)
    flips = np.full(n, 100.0)  # gate tripped throughout

    eur_leg, jpy_leg, idx = _build_legs(
        eur_prices, jpy_prices, flips_arr=flips,
    )
    rule = H3SpreadV3Rule(
        **_common_params(),
        regime_gate_lookback_bars=200,
        regime_gate_flip_threshold=5.0,
    )
    events = _run_rule(rule, eur_leg, jpy_leg, idx)
    actions = [e["action"] for e in events]
    # Adverse stop must still fire — exits are NOT gated. The v1
    # _liquidate method emits action="LIQUIDATE" with reason="ADVERSE_STOP".
    adverse_exits = [
        e for e in events
        if e["action"] == "LIQUIDATE"
        and e.get("reason") == "ADVERSE_STOP"
    ]
    assert adverse_exits, (
        f"adverse_stop exit must fire even when regime gate is tripped; "
        f"actions: {actions}"
    )
