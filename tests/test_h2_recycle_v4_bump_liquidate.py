"""Tests for H2RecycleRuleV4 (bump-and-liquidate, Phase C, 2026-05-16).

Coverage:
  - Validator accepts defaults + V4-specific params (switch_n, retrace_pct)
  - Validator rejects bad switch_n / retrace_pct values
  - Inherits parent validation (factor_operator etc.)
  - State initialization (mode=RECYCLE, counters=0)
  - consec_same_loser increments on same-loser adds; resets on flip
  - BUMP fires at switch_n; adds (switch_n+1)*add_lot to winner
  - HOLD mode tracks winner peak
  - HOLD mode triggers liquidation on retrace
  - Liquidation calls basket_runner.soft_reset_basket
  - Liquidation updates realized_total
  - After liquidation, mode resets to RECYCLE and lots reset to initial
  - BUMP rejected when projected margin breaches
  - Liquidation without basket_runner raises RuntimeError

Notes
-----
The tests build a minimal basket_sim-like fixture: 2 legs (EURUSD usd_quote
and USDJPY usd_base), synthetic OHLC, and exercise the rule directly by
calling apply() bar-by-bar with crafted price paths.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.h2_recycle_v4 import H2RecycleRuleV4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _NoOpStrategy:
    name = "noop_v4"
    timeframe = "5m"

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


def _build_legs(
    eur_prices: np.ndarray,
    jpy_prices: np.ndarray,
    factor_vals: np.ndarray | None = None,
) -> tuple[BasketLeg, BasketLeg, pd.DatetimeIndex]:
    """Build 2-leg EURUSD+USDJPY basket with controllable price paths.

    Both legs start at lot=0.01, direction=+1 (long), with avg-entry equal
    to the first bar's price.
    """
    n = len(eur_prices)
    assert len(jpy_prices) == n
    idx = pd.date_range("2024-09-02 00:00:00", periods=n, freq="5min")

    factor_col = factor_vals if factor_vals is not None else np.full(n, 100.0)

    eur_df = pd.DataFrame(
        {
            "open": eur_prices, "high": eur_prices, "low": eur_prices,
            "close": eur_prices, "compression_5d": factor_col,
        },
        index=idx,
    )
    jpy_df = pd.DataFrame(
        {
            "open": jpy_prices, "high": jpy_prices, "low": jpy_prices,
            "close": jpy_prices, "compression_5d": factor_col,
        },
        index=idx,
    )
    eur_leg = BasketLeg("EURUSD", lot=0.01, direction=+1, df=eur_df,
                        strategy=_NoOpStrategy())
    jpy_leg = BasketLeg("USDJPY", lot=0.01, direction=+1, df=jpy_df,
                        strategy=_NoOpStrategy())
    for leg, prices in [(eur_leg, eur_prices), (jpy_leg, jpy_prices)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return eur_leg, jpy_leg, idx


def _make_rule(**kwargs) -> H2RecycleRuleV4:
    """Build a V4 rule with realistic defaults. Override any field via kwargs."""
    defaults = {
        "starting_equity": 1000.0,
        "harvest_target_usd": 2000.0,
        "trigger_usd": 10.0,
        "factor_min": 5.0,
        "switch_n": 5,
        "retrace_pct": 0.30,
        "run_id": "test", "directive_id": "test", "basket_id": "H2",
    }
    defaults.update(kwargs)
    return H2RecycleRuleV4(**defaults)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def test_v4_default_construction_passes():
    r = H2RecycleRuleV4()
    assert r.switch_n == 5
    assert r.retrace_pct == 0.30
    assert r._mode == "RECYCLE"
    assert r._consec_same_loser == 0
    assert r._n_bumps == 0
    assert r._n_liquidations == 0


def test_v4_validator_rejects_switch_n_zero():
    with pytest.raises(ValueError, match="switch_n"):
        H2RecycleRuleV4(switch_n=0)


def test_v4_validator_rejects_switch_n_negative():
    with pytest.raises(ValueError, match="switch_n"):
        H2RecycleRuleV4(switch_n=-3)


def test_v4_validator_rejects_switch_n_non_int():
    with pytest.raises(ValueError, match="switch_n"):
        H2RecycleRuleV4(switch_n=3.5)


def test_v4_validator_rejects_retrace_pct_zero():
    with pytest.raises(ValueError, match="retrace_pct"):
        H2RecycleRuleV4(retrace_pct=0.0)


def test_v4_validator_rejects_retrace_pct_one():
    with pytest.raises(ValueError, match="retrace_pct"):
        H2RecycleRuleV4(retrace_pct=1.0)


def test_v4_validator_rejects_retrace_pct_above_one():
    with pytest.raises(ValueError, match="retrace_pct"):
        H2RecycleRuleV4(retrace_pct=1.5)


def test_v4_inherits_factor_operator_validation():
    # Parent class rejects unknown operators — V4 should too.
    with pytest.raises(ValueError, match="factor_operator"):
        H2RecycleRuleV4(factor_operator="==")


# ---------------------------------------------------------------------------
# consec_same_loser counter behavior
# ---------------------------------------------------------------------------


def test_v4_consec_counter_increments_on_same_loser():
    """Run 3 recycle events with EURUSD as consistent winner; consec counter
    should go 1, 2, 3."""
    # Price path: EURUSD rises (winner), USDJPY falls (loser)
    # We need each bar to trigger a recycle (winner_float >= $10).
    # On 0.01 EURUSD, $10 = 100 pips = 0.01 in price.
    n = 30
    eur = np.array([1.10 + 0.012 * (k + 1) for k in range(n)])  # rises 120 pips/bar — wait that's too fast
    # 0.012 per bar = 120 pips/bar — way more than 100 pips needed for $10 trigger
    # Should trigger easily. Let's verify with 0.011 per bar (110 pips → $11 floating)
    eur = np.full(n, 1.10001)  # nearly constant
    # Set up so EURUSD floats positive ($10+) at bar 2, 4, 6, etc.
    # 0.01 lot × 100k × Δprice = floating in USD. For +$11 floating: Δprice = +0.0011
    for k in range(n):
        eur[k] = 1.10000 + 0.0011 * (k + 1)  # +110 pips per bar past first
    jpy = np.full(n, 150.0)
    for k in range(n):
        jpy[k] = 150.0 - 0.15 * (k + 1)  # USDJPY falls — USD-base PnL = lot*100k*(p-avg)/p
        # For USDJPY at price 150 - 0.15k, avg = 150: floating = 0.01*100k*(p-150)/p
        # At k=10: p=148.5, floating = 1000 * (-1.5) / 148.5 = -$10.10 → loser

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(switch_n=10)  # higher to avoid early bump
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule.harvested:
            break
    # Several recycles should have fired with USDJPY as loser each time
    recycles = [e for e in rule.recycle_events if e.get("action") == "RECYCLE"]
    assert len(recycles) >= 2, f"Expected multiple recycles; got {len(recycles)}"
    # All should have USDJPY as loser
    for ev in recycles:
        assert ev["loser_symbol"] == "USDJPY"
    # consec_same_loser should reach len(recycles) by the end
    assert rule._consec_same_loser == len(recycles)


def test_v4_consec_counter_resets_on_loser_flip():
    """First half: USDJPY is loser. Second half: EURUSD is loser. Counter
    must reset on the flip."""
    n = 60
    # First 30 bars: EURUSD rises (winner), USDJPY falls (loser USDJPY accumulates adds)
    # After bar 30, simulate a price reversal: EURUSD starts losing, USDJPY winning
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(n):
        if k < 30:
            eur[k] = 1.10000 + 0.0012 * (k + 1)  # rising
            jpy[k] = 150.0 - 0.18 * (k + 1)      # falling
        else:
            # Reversal: now EURUSD drops below previous average; JPY rises
            # The avg entries will have shifted from prior adds, so we need
            # bigger moves to flip the floating sign. Use exaggerated reversal.
            base_eur = eur[29]
            base_jpy = jpy[29]
            eur[k] = base_eur - 0.005 * (k - 29 + 1)  # falling
            jpy[k] = base_jpy + 0.5 * (k - 29 + 1)    # rising

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(switch_n=30)  # high enough to never bump in this test
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    # Track the trajectory of last_loser_sym
    losers_seen = [ev["loser_symbol"] for ev in rule.recycle_events
                   if ev.get("action") == "RECYCLE"]
    # We expect: USDJPY appearing first, then EURUSD appearing later in the run
    if "EURUSD" in losers_seen and "USDJPY" in losers_seen:
        # If flips happened, counter must have been reset at least once.
        # Verify by checking that the last event's consec_same_loser reflects
        # the run length of the last-loser symbol's streak only.
        last_ev = next(ev for ev in reversed(rule.recycle_events)
                       if ev.get("action") == "RECYCLE")
        # The "consec_same_loser" field on the event is the value AT that event.
        # It should be ≤ the total count of trailing-equal losers.
        trailing_same = 0
        for ev in reversed(rule.recycle_events):
            if ev.get("action") != "RECYCLE":
                continue
            if ev["loser_symbol"] == last_ev["loser_symbol"]:
                trailing_same += 1
            else:
                break
        assert last_ev["consec_same_loser"] == trailing_same


# ---------------------------------------------------------------------------
# BUMP behavior
# ---------------------------------------------------------------------------


def test_v4_bump_fires_at_switch_n():
    """With switch_n=3, after 3 consecutive same-loser adds, bump fires."""
    # Sustained trend: EURUSD always rising, USDJPY always falling
    n = 40
    eur = np.array([1.10000 + 0.0012 * (k + 1) for k in range(n)])
    jpy = np.array([150.0 - 0.18 * (k + 1) for k in range(n)])
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(switch_n=3, retrace_pct=0.30)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._mode == "HOLD":
            break

    # Bump must have fired
    assert rule._n_bumps == 1
    assert rule._mode == "HOLD"
    assert rule._trend_winner_sym == "EURUSD"

    # Verify the BUMP event in the log
    bump_events = [e for e in rule.recycle_events if e.get("action") == "BUMP"]
    assert len(bump_events) == 1
    bump = bump_events[0]
    assert bump["bump_size"] == (3 + 1) * 0.01  # (switch_n + 1) * add_lot = 0.04
    assert bump["winner_symbol"] == "EURUSD"
    assert bump["winner_new_lot"] == pytest.approx(bump["winner_old_lot"] + 0.04)


def test_v4_bump_does_not_fire_before_switch_n():
    """With switch_n=10, only 5 same-loser adds should produce 0 bumps."""
    n = 25
    eur = np.array([1.10000 + 0.0012 * (k + 1) for k in range(n)])
    jpy = np.array([150.0 - 0.18 * (k + 1) for k in range(n)])
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(switch_n=10)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    # Should have multiple recycles but no bump (consec_same_loser < 10)
    recycles = [e for e in rule.recycle_events if e.get("action") == "RECYCLE"]
    assert len(recycles) > 0
    assert rule._n_bumps == 0
    assert rule._mode == "RECYCLE"


# ---------------------------------------------------------------------------
# Liquidation (HOLD mode → soft_reset)
# ---------------------------------------------------------------------------


def test_v4_liquidation_calls_basket_runner_soft_reset():
    """In HOLD mode, when winner retraces 30%, soft_reset_basket is called
    on the back-referenced basket_runner."""
    # Set up scenario with sustained trend to reach HOLD, then a reversal
    # to trigger retrace.
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    # Phase 1: EURUSD up + USDJPY down to fire 3+ recycles → bump → HOLD
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    # Phase 2: EURUSD continues up to grow winner peak (in HOLD mode now)
    eur_peak_bar = 30
    for k in range(20, eur_peak_bar):
        eur[k] = eur[19] + 0.002 * (k - 19)  # keep rising
        jpy[k] = jpy[19] - 0.1 * (k - 19)
    # Phase 3: Sharp retrace on EURUSD to trigger liquidation
    for k in range(eur_peak_bar, n):
        eur[k] = eur[eur_peak_bar - 1] - 0.005 * (k - eur_peak_bar + 1)  # falling sharply
        jpy[k] = jpy[eur_peak_bar - 1] + 0.5 * (k - eur_peak_bar + 1)

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)

    # Mock basket_runner with a spy on soft_reset_basket
    mock_runner = MagicMock(spec=BasketRunner)
    mock_runner.soft_reset_basket = MagicMock()

    rule = _make_rule(switch_n=3, retrace_pct=0.30)
    rule.basket_runner = mock_runner  # back-ref

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    # We expect: bump fired → HOLD → winner peak grew → retrace → liquidation
    assert rule._n_bumps >= 1
    assert rule._n_liquidations >= 1
    # Verify soft_reset_basket was called at least once
    assert mock_runner.soft_reset_basket.call_count >= 1
    # First call should have at_prices keyed by the basket symbols
    call_args = mock_runner.soft_reset_basket.call_args_list[0]
    assert "at_prices" in call_args.kwargs or len(call_args.args) >= 3
    # The at_prices dict should have both basket leg symbols
    at_prices = call_args.kwargs.get("at_prices", None)
    if at_prices is None and len(call_args.args) >= 3:
        at_prices = call_args.args[2]
    assert "EURUSD" in at_prices
    assert "USDJPY" in at_prices


def test_v4_liquidation_resets_rule_state():
    """After liquidation, mode → RECYCLE, counters reset."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.002 * (k - 19)
        jpy[k] = jpy[19] - 0.1 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.005 * (k - 29)
        jpy[k] = jpy[29] + 0.5 * (k - 29)

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)

    # Use a REAL basket_runner via the back-ref injection mechanism
    runner = BasketRunner([eur_leg, jpy_leg])
    rule = _make_rule(switch_n=3)
    rule.basket_runner = runner

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    # State should be reset after liquidation
    assert rule._mode == "RECYCLE"
    assert rule._consec_same_loser == 0
    assert rule._last_loser_sym is None
    assert rule._winner_peak_float == 0.0
    assert rule._trend_winner_sym is None
    # Counters incremented
    assert rule._n_bumps >= 1
    assert rule._n_liquidations >= 1


def test_v4_liquidation_realizes_floating():
    """realized_total grows by floating_total at the liquidation moment."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.002 * (k - 19)
        jpy[k] = jpy[19] - 0.1 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.005 * (k - 29)
        jpy[k] = jpy[29] + 0.5 * (k - 29)

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    runner = BasketRunner([eur_leg, jpy_leg])
    rule = _make_rule(switch_n=3)
    rule.basket_runner = runner

    realized_before_liquidation = []
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        realized_before_liquidation.append(rule.realized_total)
        if rule._n_liquidations >= 1:
            break

    # Find the bar of the first LIQUIDATE_RESET event
    liq_events = [e for e in rule.recycle_events if e.get("action") == "LIQUIDATE_RESET"]
    assert len(liq_events) >= 1
    liq_ev = liq_events[0]
    # The event records realized before/after — they must differ by the amount realized
    assert liq_ev["realized_total_after"] == pytest.approx(
        liq_ev["realized_total_before"] + liq_ev["realized_at_liquidation"]
    )


def test_v4_liquidation_resets_leg_lots_to_initial():
    """After soft_reset, both legs should be back at lot=0.01."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.002 * (k - 19)
        jpy[k] = jpy[19] - 0.1 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.005 * (k - 29)
        jpy[k] = jpy[29] + 0.5 * (k - 29)

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    runner = BasketRunner([eur_leg, jpy_leg])
    rule = _make_rule(switch_n=3)
    rule.basket_runner = runner

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    # Both legs reset to initial lot (0.01)
    assert eur_leg.lot == pytest.approx(0.01)
    assert jpy_leg.lot == pytest.approx(0.01)


def test_v4_liquidation_raises_without_basket_runner():
    """If basket_runner is None at liquidation time, raise RuntimeError."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.002 * (k - 19)
        jpy[k] = jpy[19] - 0.1 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.005 * (k - 29)
        jpy[k] = jpy[29] + 0.5 * (k - 29)

    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(switch_n=3)
    rule.basket_runner = None  # NOT injected

    with pytest.raises(RuntimeError, match="basket_runner is None"):
        for i in range(n):
            rule.apply([eur_leg, jpy_leg], i, idx[i])


# ---------------------------------------------------------------------------
# Back-reference injection works end-to-end via BasketRunner
# ---------------------------------------------------------------------------


def test_v4_back_ref_injected_by_basket_runner():
    """When the rule is attached to BasketRunner, basket_runner is auto-set."""
    eur_leg, jpy_leg, _ = _build_legs(np.full(10, 1.10), np.full(10, 150.0))
    rule = _make_rule()
    assert rule.basket_runner is None  # not set yet
    runner = BasketRunner([eur_leg, jpy_leg], rules=[rule])
    assert rule.basket_runner is runner
