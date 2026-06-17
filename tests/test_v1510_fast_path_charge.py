"""Positive proof — v1.5.10 fast-path spread charge (the canonical-flip surgery).

The basket FAST PATH bypasses evaluate_bar, so v1.5.10's direction-aware spread
charge is wired by hand at two sites (V1_5_10_CANONICAL_FLIP_DESIGN §3b/§3c):

  * ENTRY  — BasketRunner._run_fast_path: long (BUY) fills at ask (raw), short
    (SELL) at bid (= ask - per-bar embedded spread).
  * EXIT   — PineRatioZRevRule._liquidate: a long position exits SELL@bid, a
    short exits BUY@ask, side keyed on leg.effective_direction (CYCLE-AWARE).

Together a round-trip pays EXACTLY ONE spread per leg per side. Both sites are a
strict no-op at spread=0 -> byte-identical to frozen v1.5.9.

This is the fast-path complement to test_v1510_basket_parity.py (which locks the
engine path); the surgery proven here never runs through evaluate_bar. Flat OHLC
is used so a round-trip's ONLY cost is the spread.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_10 import BarState
from engines.execution_fill import bar_spread, exec_fill
from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule
from tools.recycle_strategies import (
    ContinuousHoldStrategy,
    PineZRevArmedState,
    PineZRevLegStrategy,
)

SYM_A, SYM_B = "EURUSD", "USDJPY"
PRICE_A, PRICE_B = 1.10000, 150.000
SPREAD_A, SPREAD_B = 0.00050, 0.050   # price units, per leg


class _FakeRunner:
    def __init__(self, initial_lots):
        self._initial_lots = dict(initial_lots)


def _leg_df(price: float, spread: float, n: int = 16) -> pd.DataFrame:
    """Flat OHLC (constant `price`) so a round-trip's only cost is the embedded
    `spread`. Carries the regime/enrichment columns the rule + engine read, plus
    the pine signal columns and a per-bar `coint_regime` (cointegrated by default)."""
    idx = pd.date_range("2024-09-02", periods=n, freq="1D")
    close = np.full(n, price, dtype=float)
    return pd.DataFrame(
        {
            "open": close, "high": close, "low": close, "close": close,
            "atr": np.full(n, price * 0.01, dtype=float),
            "spread": np.full(n, spread, dtype=float),
            "volatility_regime": 0.0, "trend_regime": 0, "trend_label": "neutral",
            "trend_score": 0.0, "market_regime": "normal", "regime_age": 0,
            "regime_id": "NEUTRAL", "regime_age_exec": 0,
            "pine_zrev_signal": np.zeros(n, dtype=int),
            "pine_zrev_r_bar": np.full(n, 0.00733, dtype=float),
            "coint_regime": ["cointegrated"] * n,
        },
        index=idx,
    )


# ===========================================================================
# §3b — fast-path ENTRY charge (real BasketRunner._run_fast_path)
# ===========================================================================

@pytest.mark.parametrize("spread", [(SPREAD_A, SPREAD_B), (0.0, 0.0)])
def test_fast_path_entry_charge_direction_aware(monkeypatch, spread):
    """Real fast-path open: long leg fills at ask (raw open), short at bid
    (open - spread). spread=0 -> raw (byte-identical to frozen v1.5.9)."""
    monkeypatch.setattr("tools.basket_runner.apply_regime_model", lambda df: df)
    sa, sb = spread
    legs = [
        BasketLeg(SYM_A, 0.02, +1, _leg_df(PRICE_A, sa),
                  ContinuousHoldStrategy(symbol=SYM_A, direction=+1)),
        BasketLeg(SYM_B, 0.01, -1, _leg_df(PRICE_B, sb),
                  ContinuousHoldStrategy(symbol=SYM_B, direction=-1)),
    ]
    out = BasketRunner(legs=legs).run(fast_path=True)

    ta, tb = out[SYM_A][0], out[SYM_B][0]
    # Long (dir +1) entry == ask (raw open); short (dir -1) == bid (open - spread).
    assert ta["entry_price"] == pytest.approx(PRICE_A), "long entry must be raw ask"
    assert tb["entry_price"] == pytest.approx(PRICE_B - sb), "short entry must be bid"
    if sb == 0.0:
        assert tb["entry_price"] == pytest.approx(PRICE_B), "spread=0 -> no-op (raw)"


# ===========================================================================
# §3c — rule EXIT charge (real PineRatioZRevRule._liquidate) + round-trip
# ===========================================================================

@pytest.mark.parametrize("spread", [(SPREAD_A, SPREAD_B), (0.0, 0.0)])
def test_rule_exit_charge_and_round_trip_one_spread(spread):
    """Real rule liquidate (coint-break): the exit fill is charged direction-aware
    (long SELL@bid, short BUY@ask), and the round-trip (CHARGED fast-path entry +
    CHARGED exit) pays EXACTLY one spread per leg per side. spread=0 -> raw."""
    sa, sb = spread
    df_a, df_b = _leg_df(PRICE_A, sa), _leg_df(PRICE_B, sb)
    shared = PineZRevArmedState()
    leg_a = BasketLeg(SYM_A, 0.02, +1, df_a, PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    leg_b = BasketLeg(SYM_B, 0.01, -1, df_b, PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    for leg in (leg_a, leg_b):
        leg.state = BarState()
    idx = df_a.index

    rule = PineRatioZRevRule(
        n_window=10, z_entry=2.0, entry_mode="absolute",
        default_initial_lot=0.01, target_notional_per_leg_usd=10_000.0,
        shared_armed_state=shared, coint_break_exit=True,
        run_id="TEST", directive_id="TEST_DIR", basket_id="TEST_BASKET",
    )
    rule.basket_runner = _FakeRunner({SYM_A: 0.02, SYM_B: 0.01})
    rule._z_r_attached = True   # pre-populated signal columns; bypass _attach_z_r

    # Open the basket at bar 4 (LONG_SPREAD: state.direction == base direction).
    # entry_price = the CHARGED fast-path entry (§3b) so the round-trip is end-to-end.
    for leg in (leg_a, leg_b):
        row = leg.df.iloc[4]
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 4
        leg.state.entry_price = exec_fill(float(row["close"]),
                                          is_sell=(leg.direction == -1),
                                          spread=bar_spread(row))
        leg.state.entry_market_state = {"initial_stop_price": leg.state.entry_price}

    # Bar 4 apply: detects BASKET_OPEN (snapshots cycle ctx). Mark the regime
    # BROKEN on this bar so the coint-break exit fires immediately, BEFORE any
    # z-reversal logic (the break short-circuits the rest of apply).
    for df in (df_a, df_b):
        df.loc[idx[4], "coint_regime"] = "broken"
    rule.apply([leg_a, leg_b], 4, idx[4])

    for leg, price, spr in ((leg_a, PRICE_A, sa), (leg_b, PRICE_B, sb)):
        assert leg.trades, f"{leg.symbol}: expected a liquidate trade"
        t = leg.trades[-1]
        assert t["exit_source"] == "PINE_ZREV_REGIME_BREAK"
        eff = t["direction"]   # cycle-aware effective_direction captured at exit
        # Exit fill: long position exits SELL@bid (close - spread); short BUY@ask (raw).
        expected_exit = exec_fill(price, is_sell=(eff == 1), spread=spr)
        assert t["exit_price"] == pytest.approx(expected_exit), f"{leg.symbol}: exit fill"
        # Round-trip cost == exactly one spread per leg per side (flat price).
        round_trip = (t["exit_price"] - t["entry_price"]) * eff
        assert round_trip == pytest.approx(-spr), (
            f"{leg.symbol}: round-trip must pay one spread ({-spr}), got {round_trip}")
        if spr == 0.0:
            assert t["exit_price"] == pytest.approx(price), f"{leg.symbol}: spread=0 -> raw"
