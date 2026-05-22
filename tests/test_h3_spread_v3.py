"""Tests for H3SpreadV3Rule scaffold (default-off byte-equivalence to @2).

Phase B.1 of the @3 plan: confirms the new rule class instantiates
correctly, validates its new params, and -- when all @3 params are
default -- produces identical recycle_events to H3SpreadV2Rule on the
same fixture. Subsequent phases (B.3 extreme-z exit, B.4 re-entry)
will add behavioral coverage of the new mechanics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg
from tools.recycle_rules.h3_spread_v2 import H3SpreadV2Rule
from tools.recycle_rules.h3_spread_v3 import H3SpreadV3Rule


class _NoOpStrategy:
    name = "noop_h3v3"
    timeframe = "5m"

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


class _FakeRunner:
    """Minimal BasketRunner stand-in (mirrors the @2 test fixture)."""
    def __init__(self, initial_lots):
        self._initial_lots = initial_lots


def _build_legs(eur_prices, jpy_prices, cross_side_arr=None,
                initial_lot=0.10, diff_arr=None):
    """Same shape as _build_legs in test_h3_spread_v2_harvest.py with an
    optional `diff` column (used by @3 extreme-z exit in B.3 -- harmless
    in the B.1 byte-equiv test which doesn't read it)."""
    n = len(eur_prices)
    idx = pd.date_range("2024-01-01 00:00:00", periods=n, freq="5min")
    if cross_side_arr is None:
        cross_side_arr = np.full(n, 1, dtype=int)
    cols = {
        "open": eur_prices, "high": eur_prices, "low": eur_prices,
        "close": eur_prices, "cross_side": cross_side_arr,
    }
    if diff_arr is not None:
        cols["diff"] = diff_arr
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
    """Apply the rule bar-by-bar across the full fixture."""
    runner = _FakeRunner({"EURUSD": eur_leg.lot, "USDJPY": jpy_leg.lot})
    rule.basket_runner = runner
    for i, bar_ts in enumerate(idx):
        rule.apply([eur_leg, jpy_leg], i, bar_ts)
    return rule.recycle_events


def _make_params_pair(**overrides):
    """Identical param dict for both @2 and @3 instances. @3 ignores any
    @3-specific keys not present here (they default to off).

    Note: entry_delay_bars is NOT a recycle_rule param — it's consumed at
    the run_pipeline / leg-strategy layer (cross_watch_armed semantics).
    Only fields that the dataclass actually declares are passed here.
    """
    base = dict(
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
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


def test_v3_defaults_instantiate_cleanly():
    """All @3 params default to off; class instantiates without error."""
    rule = H3SpreadV3Rule(**_make_params_pair())
    assert rule.extreme_z_threshold is None
    assert rule.reentry_z_threshold is None
    assert rule.reentry_macro_check is True
    assert rule.reentry_cross_check is True
    assert rule.reentry_max_per_regime == 3
    assert rule._armed_for_reentry is False
    assert rule._n_extreme_z_exits == 0
    assert rule._n_reentries == 0
    assert rule._reentries_this_regime == 0


def test_v3_extreme_z_only_is_valid():
    """extreme_z_threshold set, reentry_z_threshold None: valid (Mechanic A
    standalone)."""
    rule = H3SpreadV3Rule(**_make_params_pair(extreme_z_threshold=2.0))
    assert rule.extreme_z_threshold == 2.0


def test_v3_extreme_plus_reentry_is_valid():
    """Both extreme + reentry thresholds set, reentry < extreme: valid."""
    rule = H3SpreadV3Rule(**_make_params_pair(
        extreme_z_threshold=2.0, reentry_z_threshold=1.0,
    ))
    assert rule.extreme_z_threshold == 2.0
    assert rule.reentry_z_threshold == 1.0


def test_v3_reentry_without_extreme_rejected():
    """reentry_z_threshold without extreme_z_threshold is meaningless."""
    with pytest.raises(ValueError, match="requires extreme_z_threshold"):
        H3SpreadV3Rule(**_make_params_pair(reentry_z_threshold=1.0))


def test_v3_reentry_greater_than_extreme_rejected():
    """reentry must be strictly less than extreme (otherwise loop)."""
    with pytest.raises(ValueError, match="must be <"):
        H3SpreadV3Rule(**_make_params_pair(
            extreme_z_threshold=2.0, reentry_z_threshold=2.0,
        ))
    with pytest.raises(ValueError, match="must be <"):
        H3SpreadV3Rule(**_make_params_pair(
            extreme_z_threshold=2.0, reentry_z_threshold=2.5,
        ))


def test_v3_negative_extreme_threshold_rejected():
    """extreme_z_threshold must be positive (sign-aware logic uses
    cycle_dir * diff > threshold)."""
    with pytest.raises(ValueError, match="must be > 0"):
        H3SpreadV3Rule(**_make_params_pair(extreme_z_threshold=-1.0))


def test_v3_non_bool_macro_check_rejected():
    """reentry_macro_check must be a bool (not an int that happens to be 1)."""
    with pytest.raises(ValueError, match="must be a bool"):
        H3SpreadV3Rule(**_make_params_pair(reentry_macro_check=1))


def test_v3_non_positive_max_per_regime_rejected():
    """reentry_max_per_regime must be a positive int (0 = effectively
    'reentry disabled', which is what reentry_z_threshold=None already
    expresses; ambiguity rejected)."""
    with pytest.raises(ValueError, match="must be a positive int"):
        H3SpreadV3Rule(**_make_params_pair(reentry_max_per_regime=0))
    with pytest.raises(ValueError, match="must be a positive int"):
        H3SpreadV3Rule(**_make_params_pair(reentry_max_per_regime=-1))


# ---------------------------------------------------------------------------
# Byte-equivalence to @2 with all @3 params default
# ---------------------------------------------------------------------------


def _strip_volatile(events):
    """Drop fields that may legitimately differ in repr but not in semantics
    (timestamps round-trip via pandas; floats stay floats; we keep all
    decision-bearing fields)."""
    return [
        {k: v for k, v in e.items() if k != "exit_prices"}
        for e in events
    ]


def test_v3_byte_equiv_to_v2_on_pyramid_then_adverse():
    """Scenario: spread runs up enough to fire 2 pyramids, then dives to
    -$25 floating (below -2% adverse stop) and the basket liquidates.
    @3 with all @3 params default must produce the IDENTICAL recycle_events
    list as @2 with the same other params.
    """
    # Construct prices: rising EUR, flat USDJPY -> floating climbs into
    # pyramid territory; then EUR cliff -> floating drops below -$20.
    n = 60
    eur = np.concatenate([
        np.linspace(1.0800, 1.0850, 30),    # rising → pyramid eligible
        np.linspace(1.0850, 1.0750, 30),    # cliff → adverse
    ])
    jpy = np.full(n, 150.0)
    eur_leg2, jpy_leg2, idx2 = _build_legs(eur, jpy)
    eur_leg3, jpy_leg3, idx3 = _build_legs(eur, jpy)

    rule2 = H3SpreadV2Rule(**_make_params_pair())
    rule3 = H3SpreadV3Rule(**_make_params_pair())  # all @3 defaults

    events2 = _run_rule(rule2, eur_leg2, jpy_leg2, idx2)
    events3 = _run_rule(rule3, eur_leg3, jpy_leg3, idx3)

    assert _strip_volatile(events2) == _strip_volatile(events3), (
        f"@3 with defaults must be byte-equivalent to @2. "
        f"@2 events: {len(events2)}, @3 events: {len(events3)}"
    )


def test_v3_byte_equiv_to_v2_on_reverse_cross_exit():
    """Scenario: spread runs up, cross_side flips mid-run -> reverse-cross
    liquidation. @3 default vs @2 must be identical."""
    n = 50
    eur = np.linspace(1.0800, 1.0900, n)
    jpy = np.full(n, 150.0)
    # cross_side: +1 for first half, -1 for second half (regime flip)
    cross = np.concatenate([np.full(25, 1, dtype=int),
                            np.full(25, -1, dtype=int)])
    eur_leg2, jpy_leg2, idx2 = _build_legs(eur, jpy, cross_side_arr=cross)
    eur_leg3, jpy_leg3, idx3 = _build_legs(eur, jpy, cross_side_arr=cross)

    rule2 = H3SpreadV2Rule(**_make_params_pair())
    rule3 = H3SpreadV3Rule(**_make_params_pair())

    events2 = _run_rule(rule2, eur_leg2, jpy_leg2, idx2)
    events3 = _run_rule(rule3, eur_leg3, jpy_leg3, idx3)

    assert _strip_volatile(events2) == _strip_volatile(events3)


def test_v3_extreme_z_state_unset_when_threshold_none():
    """When extreme_z_threshold is None, _armed_for_reentry must remain
    False across the lifetime of the rule (no path activates it)."""
    n = 50
    eur = np.linspace(1.0800, 1.0900, n)
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = H3SpreadV3Rule(**_make_params_pair())  # extreme_z=None
    _run_rule(rule, eur_leg, jpy_leg, idx)
    assert rule._armed_for_reentry is False
    assert rule._n_extreme_z_exits == 0
    assert rule._n_reentries == 0
    assert rule._reentries_this_regime == 0
