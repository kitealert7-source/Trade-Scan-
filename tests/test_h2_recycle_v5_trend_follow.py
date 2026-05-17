"""Tests for H2RecycleRuleV5 (trend-follow pyramid, 2026-05-17).

V5 is the inverse of V1/V4 — pyramids the WINNER each $10 of new loss
on the LOSER, exits on loser recovery from trough. Tests cover:

  - Validation: pyramid_increment > 0, exit_recovery > 0, hard_floor < 0,
    inherited factor_operator validation
  - State initialization: _n_pyramids=0, _loser_sym=None
  - First pyramid: fires when loser_float <= -pyramid_increment, locks
    _loser_sym and _pyramid_winner_sym
  - Subsequent pyramids: fire at $10 increments BELOW last add level
  - Loser identity locked: even if intra-bar floats flip, _loser_sym is
    fixed for the cycle
  - Exit by recovery: loser recovers exit_recovery from trough → liquidate
  - Exit by hard floor: basket floating ≤ hard_floor_loss_usd → liquidate
  - Liquidation calls basket_runner.soft_reset_basket
  - Post-liquidation state reset: ready for new pyramid cycle
  - End-to-end via BasketRunner: back-ref injected, full cycle works
  - RuntimeError if basket_runner is None at liquidation time
"""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.h2_recycle_v5 import H2RecycleRuleV5


# ---------------------------------------------------------------------------
# Fixtures (mirror the V4 test fixtures for consistency)
# ---------------------------------------------------------------------------


class _NoOpStrategy:
    name = "noop_v5"
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
    n = len(eur_prices)
    assert len(jpy_prices) == n
    idx = pd.date_range("2024-09-02 00:00:00", periods=n, freq="5min")
    factor_col = factor_vals if factor_vals is not None else np.full(n, 1.0)  # low compression = trending
    eur_df = pd.DataFrame(
        {"open": eur_prices, "high": eur_prices, "low": eur_prices,
         "close": eur_prices, "compression_5d": factor_col}, index=idx)
    jpy_df = pd.DataFrame(
        {"open": jpy_prices, "high": jpy_prices, "low": jpy_prices,
         "close": jpy_prices, "compression_5d": factor_col}, index=idx)
    eur_leg = BasketLeg("EURUSD", lot=0.01, direction=+1, df=eur_df, strategy=_NoOpStrategy())
    jpy_leg = BasketLeg("USDJPY", lot=0.01, direction=+1, df=jpy_df, strategy=_NoOpStrategy())
    for leg, prices in [(eur_leg, eur_prices), (jpy_leg, jpy_prices)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return eur_leg, jpy_leg, idx


def _make_rule(**kwargs) -> H2RecycleRuleV5:
    """V5 rule with defaults; override any field via kwargs."""
    defaults = {
        "starting_equity": 1000.0,
        "harvest_target_usd": 2000.0,
        "trigger_usd": 10.0,
        "factor_min": 5.0,
        "factor_operator": "<=",  # inverted gate: block in chop
        "pyramid_increment_usd": 10.0,
        "exit_recovery_usd": 10.0,
        "hard_floor_loss_usd": -10.0,
        "run_id": "t", "directive_id": "t", "basket_id": "H2",
    }
    defaults.update(kwargs)
    return H2RecycleRuleV5(**defaults)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_v5_default_construction_passes():
    r = H2RecycleRuleV5()
    assert r.version == 5
    assert r.pyramid_increment_usd == 10.0
    assert r.exit_recovery_usd == 10.0
    assert r.hard_floor_loss_usd == -10.0
    assert r._n_pyramids == 0
    assert r._n_liquidations == 0
    assert r._loser_sym is None


def test_v5_rejects_pyramid_increment_zero():
    with pytest.raises(ValueError, match="pyramid_increment_usd"):
        H2RecycleRuleV5(pyramid_increment_usd=0)


def test_v5_rejects_pyramid_increment_negative():
    with pytest.raises(ValueError, match="pyramid_increment_usd"):
        H2RecycleRuleV5(pyramid_increment_usd=-5)


def test_v5_rejects_exit_recovery_zero():
    with pytest.raises(ValueError, match="exit_recovery_usd"):
        H2RecycleRuleV5(exit_recovery_usd=0)


def test_v5_rejects_hard_floor_positive():
    with pytest.raises(ValueError, match="hard_floor_loss_usd"):
        H2RecycleRuleV5(hard_floor_loss_usd=10)


def test_v5_rejects_hard_floor_zero():
    with pytest.raises(ValueError, match="hard_floor_loss_usd"):
        H2RecycleRuleV5(hard_floor_loss_usd=0)


def test_v5_inherits_factor_operator_validation():
    with pytest.raises(ValueError, match="factor_operator"):
        H2RecycleRuleV5(factor_operator="==")


# ---------------------------------------------------------------------------
# First pyramid behavior
# ---------------------------------------------------------------------------


def test_v5_first_pyramid_fires_when_loser_hits_minus_10():
    """EUR rising → USDJPY losing. When USDJPY floating <= -$10, first pyramid fires."""
    n = 30
    eur = np.array([1.10000 + 0.0012 * (k + 1) for k in range(n)])  # rising 120 pips/bar
    jpy = np.array([150.0 - 0.18 * (k + 1) for k in range(n)])      # falling
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule()
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_pyramids >= 1:
            break

    assert rule._n_pyramids >= 1
    assert rule._pyramid_winner_sym == "EURUSD"  # the rising side
    assert rule._loser_sym == "USDJPY"           # the falling side
    pyramids = [e for e in rule.recycle_events if e.get("action") == "PYRAMID"]
    assert len(pyramids) >= 1
    assert pyramids[0]["winner_symbol"] == "EURUSD"
    assert pyramids[0]["loser_symbol"] == "USDJPY"


def test_v5_first_pyramid_does_not_fire_above_threshold():
    """Loser_float between -$10 and 0 should not trigger pyramid."""
    n = 30
    # Small trend — loser stays above -$10
    eur = np.array([1.10000 + 0.0005 * (k + 1) for k in range(n)])  # tiny rise
    jpy = np.array([150.0 - 0.05 * (k + 1) for k in range(n)])      # tiny fall
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule()
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    # Loser float should be small; no pyramid
    assert rule._n_pyramids == 0


# ---------------------------------------------------------------------------
# Subsequent pyramids fire at $10 increments
# ---------------------------------------------------------------------------


def test_v5_subsequent_pyramids_fire_at_10_dollar_increments():
    """After first pyramid at loser=-$10, next fires at -$20, then -$30."""
    n = 60
    eur = np.array([1.10000 + 0.0012 * (k + 1) for k in range(n)])
    jpy = np.array([150.0 - 0.18 * (k + 1) for k in range(n)])
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule()
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    pyramids = [e for e in rule.recycle_events if e.get("action") == "PYRAMID"]
    assert len(pyramids) >= 2
    # Loser_float at successive pyramids should be ~$10 apart (monotonically decreasing)
    for k in range(1, len(pyramids)):
        delta = pyramids[k]["cur_loser_float"] - pyramids[k - 1]["cur_loser_float"]
        assert delta <= -10.0 + 1e-6, (
            f"Pyramid {k} fired at loser_float={pyramids[k]['cur_loser_float']:.2f} but "
            f"previous was {pyramids[k-1]['cur_loser_float']:.2f} — delta {delta:.2f} "
            f"should be ≤ -$10"
        )


def test_v5_loser_identity_locked_after_first_pyramid():
    """Once we start pyramiding direction X, the loser_sym stays fixed for the cycle."""
    n = 40
    eur = np.array([1.10000 + 0.0012 * (k + 1) for k in range(n)])
    jpy = np.array([150.0 - 0.18 * (k + 1) for k in range(n)])
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule()
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    assert rule._loser_sym == "USDJPY"
    # Within the cycle, every pyramid event should have same loser_symbol
    pyramids = [e for e in rule.recycle_events if e.get("action") == "PYRAMID"]
    assert all(p["loser_symbol"] == "USDJPY" for p in pyramids)


# ---------------------------------------------------------------------------
# Pyramid trigger respects regime gate
# ---------------------------------------------------------------------------


def test_v5_regime_gate_blocks_pyramid():
    """With factor_operator='<=' and factor_min=5 and compression_5d=10 → gate fires (block)."""
    n = 30
    eur = np.array([1.10000 + 0.0012 * (k + 1) for k in range(n)])
    jpy = np.array([150.0 - 0.18 * (k + 1) for k in range(n)])
    high_compression = np.full(n, 10.0)  # chop — high compression > 5 → gate blocks
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, factor_vals=high_compression)
    rule = _make_rule(factor_operator="<=", factor_min=5.0)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    # Pyramid should be blocked
    assert rule._n_pyramids == 0
    # Bars should be recorded with skip_reason REGIME_GATE
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "REGIME_GATE" in reasons


# ---------------------------------------------------------------------------
# Exit triggers
# ---------------------------------------------------------------------------


def test_v5_liquidation_calls_basket_runner_soft_reset():
    """Sustained trend → multiple pyramids → reversal → loser recovers $10 from trough → liquidate."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    # Phase 1: trend builds (loser drops to ~-$30)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    # Phase 2: peak (extended trend)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.001 * (k - 19)
        jpy[k] = jpy[19] - 0.10 * (k - 19)
    # Phase 3: reversal — loser recovers
    for k in range(30, n):
        eur[k] = eur[29] - 0.003 * (k - 29)
        jpy[k] = jpy[29] + 0.30 * (k - 29)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)

    mock_runner = MagicMock(spec=BasketRunner)
    mock_runner.soft_reset_basket = MagicMock()
    rule = _make_rule()
    rule.basket_runner = mock_runner

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    # Liquidation resets _n_pyramids to 0; verify via the event log instead.
    pyramid_events = [e for e in rule.recycle_events if e.get("action") == "PYRAMID"]
    assert len(pyramid_events) >= 1
    assert rule._n_liquidations >= 1
    assert mock_runner.soft_reset_basket.call_count >= 1


def test_v5_liquidation_resets_rule_state():
    """After liquidation, _n_pyramids=0, _loser_sym=None, etc."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.001 * (k - 19)
        jpy[k] = jpy[19] - 0.10 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.003 * (k - 29)
        jpy[k] = jpy[29] + 0.30 * (k - 29)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    runner = BasketRunner([eur_leg, jpy_leg])
    rule = _make_rule()
    rule.basket_runner = runner

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    assert rule._n_pyramids == 0
    assert rule._loser_sym is None
    assert rule._pyramid_winner_sym is None
    assert rule._loser_trough_float == 0.0
    assert rule._last_add_loser_level == 0.0
    assert rule._n_liquidations >= 1


def test_v5_liquidation_resets_leg_lots_to_initial():
    """After soft_reset, both legs back at initial 0.01."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.001 * (k - 19)
        jpy[k] = jpy[19] - 0.10 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.003 * (k - 29)
        jpy[k] = jpy[29] + 0.30 * (k - 29)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    runner = BasketRunner([eur_leg, jpy_leg])
    rule = _make_rule()
    rule.basket_runner = runner

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    assert eur_leg.lot == pytest.approx(0.01)
    assert jpy_leg.lot == pytest.approx(0.01)


def test_v5_liquidation_realizes_floating():
    """realized_total grows by floating_total at liquidation moment."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.001 * (k - 19)
        jpy[k] = jpy[19] - 0.10 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.003 * (k - 29)
        jpy[k] = jpy[29] + 0.30 * (k - 29)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    runner = BasketRunner([eur_leg, jpy_leg])
    rule = _make_rule()
    rule.basket_runner = runner

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
        if rule._n_liquidations >= 1:
            break

    liq_events = [e for e in rule.recycle_events
                  if e.get("action") in ("TREND_LIQUIDATE_RECOVERY", "TREND_LIQUIDATE_FLOOR")]
    assert len(liq_events) >= 1
    ev = liq_events[0]
    assert ev["realized_total_after"] == pytest.approx(
        ev["realized_total_before"] + ev["realized_at_liquidation"]
    )


def test_v5_liquidation_raises_without_basket_runner():
    """If basket_runner is None when liquidation fires, raise RuntimeError."""
    n = 60
    eur = np.zeros(n)
    jpy = np.zeros(n)
    for k in range(20):
        eur[k] = 1.10000 + 0.0015 * (k + 1)
        jpy[k] = 150.0 - 0.20 * (k + 1)
    for k in range(20, 30):
        eur[k] = eur[19] + 0.001 * (k - 19)
        jpy[k] = jpy[19] - 0.10 * (k - 19)
    for k in range(30, n):
        eur[k] = eur[29] - 0.003 * (k - 29)
        jpy[k] = jpy[29] + 0.30 * (k - 29)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule()
    rule.basket_runner = None

    with pytest.raises(RuntimeError, match="basket_runner is None"):
        for i in range(n):
            rule.apply([eur_leg, jpy_leg], i, idx[i])


# ---------------------------------------------------------------------------
# Back-reference injection via BasketRunner
# ---------------------------------------------------------------------------


def test_v5_back_ref_injected_by_basket_runner():
    eur_leg, jpy_leg, _ = _build_legs(np.full(10, 1.10), np.full(10, 150.0))
    rule = _make_rule()
    assert rule.basket_runner is None
    runner = BasketRunner([eur_leg, jpy_leg], rules=[rule])
    assert rule.basket_runner is runner
