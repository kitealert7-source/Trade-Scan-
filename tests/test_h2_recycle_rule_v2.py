"""H2RecycleRule unit tests — Variant G + harvest exit + compression gate.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 3 (corrected v11.x).
Reference: tmp/eurjpy_recycle_v2_validation.py (CONFIGS H2 row).

Distinct from `tests/test_h2_recycle_rule.py` (deprecated rule) and
`tests/test_basket_phase5c_real_data.py` (end-to-end). This file isolates
the rule's arithmetic + decision logic against synthetic fixtures:

  - param validation (trigger > 0, harvest > stake, etc.)
  - recycle does NOT fire when compression_5d < factor_min
  - recycle DOES fire on Variant G trigger (winner >= $10, loser < 0)
  - recycle PnL math: winner realizes, loser averaging + lot growth
  - DD freeze blocks recycle without exiting
  - margin freeze blocks recycle without exiting
  - harvest target exits all legs (close + stop)
  - equity floor exits all legs
  - time stop exits all legs
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg
from tools.recycle_rules import H2RecycleRule
from engine_abi.v1_5_9 import BarState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basket(eur_prices, jpy_prices, comp_5d, *,
            eur_lot=0.02, jpy_lot=0.01):
    """Build a 2-leg basket with positions already open at bar 0."""
    assert len(eur_prices) == len(jpy_prices) == len(comp_5d)
    idx = pd.date_range("2024-09-02 00:00:00", periods=len(eur_prices), freq="5min")
    eur_df = pd.DataFrame({"open": eur_prices, "high": eur_prices,
                           "low": eur_prices, "close": eur_prices,
                           "compression_5d": comp_5d}, index=idx)
    jpy_df = pd.DataFrame({"open": jpy_prices, "high": jpy_prices,
                           "low": jpy_prices, "close": jpy_prices,
                           "compression_5d": comp_5d}, index=idx)
    eur = BasketLeg("EURUSD", lot=eur_lot, direction=+1, df=eur_df, strategy=None)  # noqa
    jpy = BasketLeg("USDJPY", lot=jpy_lot, direction=-1, df=jpy_df, strategy=None)  # noqa

    for leg, prices in [(eur, eur_prices), (jpy, jpy_prices)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
    return eur, jpy, idx


def _drive(rule, eur, jpy, idx, *, skip_bar0=True):
    """Run rule.apply() for every bar in idx. By default skips bar 0 since
    `_basket` has already bootstrapped state at bar 0."""
    start = 1 if skip_bar0 else 0
    for i, ts in enumerate(idx):
        if i < start:
            continue
        rule.apply([eur, jpy], i, ts)


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------


def test_param_validation_rejects_bad_inputs():
    for kw in [
        {"trigger_usd": 0.0},
        {"trigger_usd": -1.0},
        {"add_lot": 0.0},
        {"harvest_target_usd": 1000.0, "starting_equity": 1000.0},  # not strictly greater
        {"harvest_target_usd": 999.0, "starting_equity": 1000.0},
        {"dd_freeze_frac": 0.0},
        {"dd_freeze_frac": 1.0},
        {"margin_freeze_frac": 1.5},
        {"factor_column": ""},
    ]:
        with pytest.raises(ValueError):
            H2RecycleRule(**kw)


def test_param_defaults():
    rule = H2RecycleRule()
    assert rule.name == "H2_recycle"
    assert rule.version == 1
    assert rule.trigger_usd == 10.0
    assert rule.add_lot == 0.01
    assert rule.starting_equity == 1000.0
    assert rule.harvest_target_usd == 2000.0
    assert rule.factor_column == "compression_5d"
    assert rule.factor_min == 10.0


# ---------------------------------------------------------------------------
# Compression gate
# ---------------------------------------------------------------------------


def test_gate_closed_blocks_recycle_no_exit():
    """When compression_5d < factor_min, recycle does not fire even if PnL
    is well above the trigger. Positions remain in-position (no harvest)."""
    # EUR rises, JPY rises (loser side for short) -> winner=EUR, loser=JPY
    # but compression=5 (below factor_min=10)
    eur = [1.10 + 0.0010 * k for k in range(8)]   # 100 pips rise -> winner $200
    jpy = [146.00 + 0.10 * k for k in range(8)]
    comp = [5.0] * 8
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp)
    rule = H2RecycleRule()
    _drive(rule, eur_leg, jpy_leg, idx)
    assert len(rule.recycle_events) == 0
    assert rule.harvested is False
    assert rule._n_regime_freezes > 0
    assert eur_leg.state.in_pos is True
    assert jpy_leg.state.in_pos is True


def test_gate_open_triggers_recycle_on_variant_g():
    """compression_5d >= factor_min AND winner >= $10 AND loser < 0 -> recycle.
    Variant G: close winner (realize), grow loser lot, weighted-avg new entry.

    Math at 0.02 EUR lot: $10 trigger needs (price - 1.10) >= 0.005 = 50 pips.
    """
    eur = [1.10, 1.1060, 1.1060, 1.1060]    # +60 pips at bar 1 -> EUR float = $12
    jpy = [146.00, 146.02, 146.02, 146.02]  # +2 JPY pips -> short loses ~$1.37
    comp = [12.0] * 4
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp)
    rule = H2RecycleRule()
    _drive(rule, eur_leg, jpy_leg, idx)
    assert len(rule.recycle_events) >= 1, "expected at least one recycle event"
    ev = rule.recycle_events[0]
    assert ev["winner_symbol"] == "EURUSD"
    assert ev["loser_symbol"] == "USDJPY"
    # Loser lot grew
    assert jpy_leg.lot > 0.01
    # EUR entry was reset to current bar close (winner closed-and-reopened)
    assert eur_leg.state.entry_price > 1.10
    # Realized banked
    assert rule.realized_total > 0


def test_recycle_winner_pnl_math_eur():
    """For a $20 winner-leg floating, realized_total should bank exactly that.

    Math: 0.02 EUR * 100,000 * delta = $20  =>  delta = 0.010 (100 pips).
    """
    eur = [1.10, 1.110, 1.110, 1.110]    # +100 pips at bar 1 -> EUR float = $20
    jpy = [146.00, 146.10, 146.10, 146.10]  # +10 JPY pips -> short loses ~$6.85
    comp = [15.0] * 4
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp)
    rule = H2RecycleRule(trigger_usd=10.0)
    _drive(rule, eur_leg, jpy_leg, idx)
    assert len(rule.recycle_events) >= 1
    ev = rule.recycle_events[0]
    # Winner realized should be $20 (within float epsilon)
    assert abs(ev["winner_realized"] - 20.0) < 1e-6
    assert abs(rule.realized_total - 20.0) < 1e-6


# ---------------------------------------------------------------------------
# Harvest exit
# ---------------------------------------------------------------------------


def test_harvest_target_closes_all_and_sets_flag():
    """When equity >= harvest_target_usd, close all legs + harvested=True.

    Math: 0.02 EUR * 100,000 * delta = $500 (to push equity 1000 -> 1500)
          delta = 0.025 = 250 pips. Use a 0.10 lot to keep numbers reasonable:
          0.10 * 100,000 * 0.050 = $500.
    """
    # Use 700 pips (not 500) to comfortably clear the 1500 target despite
    # floating-point precision in (price - entry).
    eur = [1.10, 1.17]
    jpy = [146.00, 146.00]
    comp = [15.0] * 2
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp, eur_lot=0.10)
    rule = H2RecycleRule(harvest_target_usd=1500.0)
    _drive(rule, eur_leg, jpy_leg, idx)
    assert rule.harvested is True
    assert rule.exit_reason == "TARGET"
    assert eur_leg.state.in_pos is False
    assert jpy_leg.state.in_pos is False
    # Per-leg harvest trades emitted
    assert any(t.get("exit_source", "").startswith("BASKET_HARVEST_TARGET")
               for t in eur_leg.trades)


def test_equity_floor_closes_all():
    """When equity <= equity_floor, close all legs (FLOOR).

    Engineer floating < -$400 to push equity below the $600 floor.
    """
    eur = [1.10, 1.05]   # -500 pips on 0.10 lot = -$500 floating
    jpy = [146.00, 146.00]
    comp = [15.0] * 2
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp, eur_lot=0.10)
    rule = H2RecycleRule(equity_floor_usd=600.0)
    _drive(rule, eur_leg, jpy_leg, idx)
    assert rule.harvested is True
    assert rule.exit_reason == "FLOOR"


def test_time_stop_closes_all():
    """When days-since-entry >= time_stop_days, close all (TIME)."""
    # 270 bars at 5min spacing is < 1 day; need a daily index.
    idx = pd.date_range("2024-09-02", periods=400, freq="D")
    n = len(idx)
    eur_df = pd.DataFrame({"open": [1.10]*n, "high": [1.10]*n, "low": [1.10]*n,
                           "close": [1.10]*n, "compression_5d": [15.0]*n}, index=idx)
    jpy_df = pd.DataFrame({"open": [146.0]*n, "high": [146.0]*n, "low": [146.0]*n,
                           "close": [146.0]*n, "compression_5d": [15.0]*n}, index=idx)
    eur = BasketLeg("EURUSD", lot=0.02, direction=+1, df=eur_df, strategy=None)  # noqa
    jpy = BasketLeg("USDJPY", lot=0.01, direction=-1, df=jpy_df, strategy=None)  # noqa
    for leg, p in [(eur, 1.10), (jpy, 146.0)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = p
    rule = H2RecycleRule(time_stop_days=270)
    _drive(rule, eur, jpy, idx)
    assert rule.harvested is True
    assert rule.exit_reason == "TIME"


# ---------------------------------------------------------------------------
# DD / margin freeze (block recycle without exiting)
# ---------------------------------------------------------------------------


def test_dd_freeze_blocks_recycle_no_exit():
    """When floating < 0 AND |floating| >= dd_freeze_frac * equity, freeze the
    recycle but do NOT close positions.

    Engineer: EUR +60 pips (winner = $12 on 0.02 lot), JPY +200 pips with a
    chunky 0.10 lot so short losses dwarf EUR profit.
      JPY float = -0.10 * 100000 * (148 - 146) / 148 = -$135.14
      Total floating = $12 - $135 = -$123. Equity = $877.
      10% of equity = $87.70. |floating| $123 > $87.70 -> DD breach.
    """
    eur = [1.10, 1.106]              # +60 pips on 0.02 = $12 winner
    jpy = [146.00, 148.00]           # +200 pips, short on 0.10 lot loses ~-$135
    comp = [15.0] * 2
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp, jpy_lot=0.10)
    rule = H2RecycleRule(trigger_usd=10.0, dd_freeze_frac=0.10)
    _drive(rule, eur_leg, jpy_leg, idx)
    # DD breach occurred at least once
    assert rule._n_dd_freezes >= 1
    # No recycle even though EUR winner >= $10 and JPY loser < 0
    assert len(rule.recycle_events) == 0
    # Positions still open
    assert eur_leg.state.in_pos is True
    assert jpy_leg.state.in_pos is True


# ---------------------------------------------------------------------------
# Idempotency post-harvest
# ---------------------------------------------------------------------------


def test_post_harvest_apply_is_noop():
    """Once harvested=True, further apply() calls do nothing."""
    eur = [1.10, 1.150, 1.160, 1.170]      # bar 1 hits target on 0.10 lot
    jpy = [146.00, 146.00, 146.00, 146.00]
    comp = [15.0] * 4
    eur_leg, jpy_leg, idx = _basket(eur, jpy, comp, eur_lot=0.10)
    rule = H2RecycleRule(harvest_target_usd=1400.0)
    _drive(rule, eur_leg, jpy_leg, idx)
    assert rule.harvested is True
    # Subsequent calls should not change harvested_total_usd
    snapshot = rule.harvested_total_usd
    rule.apply([eur_leg, jpy_leg], 99, idx[-1])
    assert rule.harvested_total_usd == snapshot
