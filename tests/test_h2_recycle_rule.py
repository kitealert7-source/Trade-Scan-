"""Phase 3 unit test — H2CompressionRecycleRule mechanics.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 3.

This is a focused unit test of the rule's `apply()` method. The full
end-to-end bit-for-bit parity vs `tools/research/basket_sim.py` over 10
historical 2y windows is the Phase 5 acceptance gate (it requires a real
basket directive running through the pipeline). Here we verify the rule's
deterministic basket-level behavior:

  - gate-closed bars never trigger a recycle, regardless of PnL
  - gate-open bars below harvest_threshold never trigger a recycle
  - gate-open bars at-or-above harvest_threshold:
      * close BOTH legs (BASKET_RECYCLE exit trade per leg)
      * harvest the floating PnL into harvested_total_usd
      * re-open BOTH legs at the same direction/lot at current bar close
  - PnL math matches the per-convention formulas
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules import H2CompressionRecycleRule
from engine_abi.v1_5_9 import BarState


# ---------------------------------------------------------------------------
# Synthetic fixture: linear EUR-up + JPY-down with a compression-gate flip
# ---------------------------------------------------------------------------


def _make_h2_basket(eur_prices, jpy_prices, compression_5d) -> tuple[BasketLeg, BasketLeg, pd.DatetimeIndex]:
    assert len(eur_prices) == len(jpy_prices) == len(compression_5d)
    idx = pd.date_range("2024-09-02 00:00:00", periods=len(eur_prices), freq="5min")
    eur_df = pd.DataFrame(
        {"open": eur_prices, "high": eur_prices, "low": eur_prices,
         "close": eur_prices, "compression_5d": compression_5d},
        index=idx,
    )
    jpy_df = pd.DataFrame(
        {"open": jpy_prices, "high": jpy_prices, "low": jpy_prices,
         "close": jpy_prices, "compression_5d": compression_5d},
        index=idx,
    )
    eur_leg = BasketLeg("EURUSD", lot=0.02, direction=+1, df=eur_df, strategy=None)  # noqa
    jpy_leg = BasketLeg("USDJPY", lot=0.01, direction=-1, df=jpy_df, strategy=None)  # noqa
    # Bootstrap "already-entered" state at bar 0 (this test bypasses evaluate_bar)
    eur_leg.state = BarState()
    eur_leg.state.in_pos = True
    eur_leg.state.direction = +1
    eur_leg.state.entry_index = 0
    eur_leg.state.entry_price = float(eur_prices[0])
    eur_leg.state.entry_market_state = {"initial_stop_price": 0.0}

    jpy_leg.state = BarState()
    jpy_leg.state.in_pos = True
    jpy_leg.state.direction = -1
    jpy_leg.state.entry_index = 0
    jpy_leg.state.entry_price = float(jpy_prices[0])
    jpy_leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return eur_leg, jpy_leg, idx


def _drive_rule(rule: H2CompressionRecycleRule, eur_leg: BasketLeg, jpy_leg: BasketLeg, idx) -> None:
    """Simulate BasketRunner's per-bar rule invocation without evaluate_bar.

    Phase 2 test already proves BasketRunner sequencing is correct; this
    test isolates the rule's own arithmetic and event emission.
    """
    for i, ts in enumerate(idx):
        rule.apply([eur_leg, jpy_leg], i, ts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_rule_registers_name_and_version():
    rule = H2CompressionRecycleRule(
        threshold=10.0, stake_usd=1000.0, harvest_threshold_usd=2000.0,
        factor_column="compression_5d",
    )
    assert rule.name == "H2_v7_compression"
    assert rule.version == 1


def test_gate_closed_never_recycles():
    # Compression below threshold for the whole window — gate never opens.
    n = 50
    eur = 1.10 + np.linspace(0, 0.05, n)   # large unrealized profit on long
    jpy = 150.0 - np.linspace(0, 5.0, n)   # large unrealized profit on short
    comp = np.full(n, 5.0)                  # below threshold of 10
    eur_leg, jpy_leg, idx = _make_h2_basket(eur, jpy, comp)

    rule = H2CompressionRecycleRule(
        threshold=10.0, stake_usd=1000.0, harvest_threshold_usd=100.0,
        factor_column="compression_5d",
    )
    _drive_rule(rule, eur_leg, jpy_leg, idx)

    assert rule.recycle_events == []
    assert rule.harvested_total_usd == 0.0
    # Positions remain open at their original entries.
    assert eur_leg.state.in_pos and eur_leg.state.entry_index == 0
    assert jpy_leg.state.in_pos and jpy_leg.state.entry_index == 0


def test_gate_open_below_threshold_never_recycles():
    n = 50
    eur = np.full(n, 1.10001)              # near-zero PnL
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)                # gate open
    eur_leg, jpy_leg, idx = _make_h2_basket(eur, jpy, comp)
    rule = H2CompressionRecycleRule(
        threshold=10.0, stake_usd=1000.0, harvest_threshold_usd=2000.0,  # high bar
        factor_column="compression_5d",
    )
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    assert rule.recycle_events == []


def test_recycle_triggers_when_gate_open_and_pnl_above_threshold():
    """First half of the window: gate closed, prices drift up.
    Second half: gate opens. Combined PnL crosses harvest_threshold and
    triggers a recycle."""
    n = 100
    eur = np.concatenate([
        np.linspace(1.10, 1.115, 50),   # +1.5 pips * 0.02 lot * 100000 = ~$30
        np.linspace(1.115, 1.13, 50),
    ])
    jpy = np.concatenate([
        np.linspace(150.0, 147.0, 50),  # -3 yen on short 0.01 lot ~$20+
        np.linspace(147.0, 145.0, 50),
    ])
    comp = np.concatenate([np.full(50, 5.0), np.full(50, 15.0)])
    eur_leg, jpy_leg, idx = _make_h2_basket(eur, jpy, comp)

    rule = H2CompressionRecycleRule(
        threshold=10.0, stake_usd=1000.0, harvest_threshold_usd=40.0,
        factor_column="compression_5d",
    )
    _drive_rule(rule, eur_leg, jpy_leg, idx)

    assert len(rule.recycle_events) >= 1, "expected at least one recycle event"
    ev = rule.recycle_events[0]
    # Recycle must fire on or after bar 50 (gate flips at 50)
    assert ev["bar_index"] >= 50
    assert ev["factor_value"] >= 10.0
    assert ev["floating_pnl_usd"] >= 40.0

    # After recycle: legs were closed (one exit trade each) and re-opened
    # at the bar close.
    assert len(eur_leg.trades) >= 1, eur_leg.trades
    assert len(jpy_leg.trades) >= 1, jpy_leg.trades
    assert eur_leg.trades[0]["exit_source"] == "BASKET_RECYCLE"
    assert jpy_leg.trades[0]["exit_source"] == "BASKET_RECYCLE"
    assert eur_leg.state.in_pos  # re-opened
    assert jpy_leg.state.in_pos  # re-opened
    # The state reflects the LATEST recycle event, since multiple may fire
    # over the window (prices keep drifting -> threshold crossed again).
    last_ev = rule.recycle_events[-1]
    last_i = last_ev["bar_index"]
    assert eur_leg.state.entry_price == eur[last_i]
    assert jpy_leg.state.entry_price == jpy[last_i]
    # Harvested total equals sum of per-event floating PnL.
    assert abs(rule.harvested_total_usd - sum(e["floating_pnl_usd"] for e in rule.recycle_events)) < 1e-9


def test_pnl_math_per_convention():
    """Spot-check the per-convention PnL formula at one bar."""
    eur = np.array([1.10, 1.12])           # +200 pips on EURUSD
    jpy = np.array([150.0, 145.0])         # USDJPY drops 5 yen
    comp = np.array([15.0, 15.0])
    eur_leg, jpy_leg, idx = _make_h2_basket(eur, jpy, comp)
    rule = H2CompressionRecycleRule(
        threshold=10.0, stake_usd=1000.0,
        harvest_threshold_usd=1.0,  # very low — must trigger on bar 1
        factor_column="compression_5d",
    )
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    ev = rule.recycle_events[0]
    # EURUSD long 0.02 lot: pnl = 0.02 * 100000 * (1.12 - 1.10) = 40.00
    # USDJPY short 0.01 lot: pnl = -1 * 0.01 * 100000 * (145.0 - 150.0) / 145.0
    #                            = -1 * 1000 * -5 / 145 = +5000/145 ~= 34.4828
    expected_eur = 0.02 * 100_000 * (1.12 - 1.10)
    expected_jpy = -1 * 0.01 * 100_000 * (145.0 - 150.0) / 145.0
    expected_total = expected_eur + expected_jpy
    assert abs(ev["floating_pnl_usd"] - expected_total) < 1e-6, (
        f"PnL math drift: got {ev['floating_pnl_usd']}, expected {expected_total}"
    )


def test_param_validation():
    import pytest
    base = dict(threshold=10.0, stake_usd=1000.0,
                harvest_threshold_usd=2000.0, factor_column="compression_5d")
    for k in ("threshold", "stake_usd", "harvest_threshold_usd"):
        kw = dict(base); kw[k] = -1.0
        with pytest.raises(ValueError):
            H2CompressionRecycleRule(**kw)
    kw = dict(base); kw["factor_column"] = ""
    with pytest.raises(ValueError):
        H2CompressionRecycleRule(**kw)
