"""Unit tests for the 1.3.0-basket per-bar ledger emit in H2RecycleRule.

Plan ref: outputs/H2_BASKET_TELEMETRY_IMPLEMENTATION_PLAN.md §8 (unit tests 1-8).
Operator-approved 2026-05-16.

Tests the rule's per_bar_records emission and summary_stats accumulator in
isolation. Driven by direct apply() calls with controlled fixture prices +
factor values, bypassing BasketRunner.run().
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules import H2RecycleRule
from engine_abi.v1_5_9 import BarState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_basket(eur, jpy, comp, *, eur_lot=0.02, jpy_lot=0.01):
    """Build a 2-leg basket (EURUSD long + USDJPY long) with prices + factor."""
    n = len(eur)
    assert len(jpy) == n == len(comp)
    idx = pd.date_range("2024-09-02 00:00:00", periods=n, freq="5min")
    eur_df = pd.DataFrame(
        {"open": eur, "high": eur, "low": eur, "close": eur, "compression_5d": comp},
        index=idx,
    )
    jpy_df = pd.DataFrame(
        {"open": jpy, "high": jpy, "low": jpy, "close": jpy, "compression_5d": comp},
        index=idx,
    )
    eur_leg = BasketLeg("EURUSD", lot=eur_lot, direction=+1, df=eur_df, strategy=None)  # type: ignore[arg-type]
    jpy_leg = BasketLeg("USDJPY", lot=jpy_lot, direction=+1, df=jpy_df, strategy=None)  # type: ignore[arg-type]
    for leg, prices in [(eur_leg, eur), (jpy_leg, jpy)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return eur_leg, jpy_leg, idx


def _drive_rule(rule, eur_leg, jpy_leg, idx, *, start=0):
    """Invoke rule.apply() over the index range (starting at bar `start`)."""
    for i in range(start, len(idx)):
        rule.apply([eur_leg, jpy_leg], i, idx[i])


def _default_rule(**overrides):
    """H2RecycleRule with safe-test defaults; identity threading on."""
    params = dict(
        trigger_usd=10.0,
        add_lot=0.01,
        starting_equity=1000.0,
        harvest_target_usd=2000.0,
        dd_freeze_frac=0.10,
        margin_freeze_frac=0.15,
        leverage=1000.0,
        factor_column="compression_5d",
        factor_min=10.0,
        run_id="test_run_id",
        directive_id="test_directive",
        basket_id="H2",
    )
    params.update(overrides)
    return H2RecycleRule(**params)


# ---------------------------------------------------------------------------
# Test 1 — per_bar_records populated
# ---------------------------------------------------------------------------


def test_per_bar_records_populated():
    """50-bar flat run leaves 50 per_bar_records with identity threading filled."""
    n = 50
    eur = np.full(n, 1.10001)
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    assert len(rule.per_bar_records) == n
    for rec in rule.per_bar_records:
        assert rec["directive_id"] == "test_directive"
        assert rec["basket_id"] == "H2"
        assert rec["run_id"] == "test_run_id"


# ---------------------------------------------------------------------------
# Test 2 — skip_reason enum coverage (split across paths)
# ---------------------------------------------------------------------------


def test_skip_reason_no_winner():
    """Flat prices → no leg crosses trigger → NO_WINNER."""
    n = 20
    eur = np.full(n, 1.10001)
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "NO_WINNER" in reasons


def test_skip_reason_no_loser():
    """Both legs profitable → winner found but no loser → NO_LOSER."""
    n = 20
    eur = np.linspace(1.100, 1.110, n)   # +$20 floating at end
    jpy = np.linspace(150.0, 151.5, n)   # USDJPY long: also positive
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "NO_LOSER" in reasons


def test_skip_reason_dd_freeze():
    """Deep negative floating → dd_breach → DD_FREEZE."""
    n = 20
    eur = np.linspace(1.100, 1.050, n)   # PnL ~ -$100 at end
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "DD_FREEZE" in reasons
    assert rule.summary_stats["dd_freeze_count"] >= 1


def test_skip_reason_regime_gate():
    """Factor below min → gate blocks → REGIME_GATE."""
    n = 20
    eur = np.full(n, 1.10001)
    jpy = np.full(n, 150.0)
    comp = np.full(n, 5.0)               # below factor_min=10
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "REGIME_GATE" in reasons
    assert rule.summary_stats["regime_freeze_count"] >= 1


def test_skip_reason_rule_not_invoked_missing_factor():
    """Factor column absent from primary leg → RULE_NOT_INVOKED."""
    n = 20
    eur = np.full(n, 1.10001)
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    eur_leg.df = eur_leg.df.drop(columns=["compression_5d"])
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "RULE_NOT_INVOKED" in reasons


# ---------------------------------------------------------------------------
# Test 3 — recycle_executed flag
# ---------------------------------------------------------------------------


def test_recycle_executed_flag():
    """Setup with winner + loser → recycle commits; flag fires on those bars only."""
    n = 20
    eur = np.linspace(1.100, 1.115, n)   # EUR long winner
    jpy = np.linspace(150.0, 149.0, n)   # USDJPY long loser
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    executed = [r for r in rule.per_bar_records if r["recycle_executed"]]
    skip_set = {r["skip_reason"] for r in rule.per_bar_records}
    assert len(executed) >= 1, f"expected at least one recycle; skip_reasons: {skip_set}"
    assert len(rule.recycle_events) == len(executed)
    # All non-executed bars have recycle_executed=False
    not_executed = [r for r in rule.per_bar_records if not r["recycle_executed"]]
    for r in not_executed:
        assert r["winner_leg_idx"] is None
        assert r["loser_leg_idx"] is None


# ---------------------------------------------------------------------------
# Test 4 — harvest_triggered terminal
# ---------------------------------------------------------------------------


def test_harvest_triggered_terminal():
    """Harvest fires → last record has harvest_triggered=True; summary_stats finalized."""
    n = 30
    eur = np.linspace(1.100, 1.600, n)   # +$1000 floating → equity = $2000
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    assert rule.harvested
    assert rule.per_bar_records[-1]["harvest_triggered"] is True
    for r in rule.per_bar_records[:-1]:
        assert r["harvest_triggered"] is False
    assert rule.summary_stats["final_pnl_usd"] is not None
    assert rule.summary_stats["harvest_reason"] == "TARGET"
    assert rule.summary_stats["harvest_bar_index"] is not None


# ---------------------------------------------------------------------------
# Test 5 — no records after harvest
# ---------------------------------------------------------------------------


def test_no_records_after_harvest():
    """Calling apply() after harvest does not append more records."""
    n = 20
    eur = np.linspace(1.100, 1.700, n)   # forces harvest mid-run
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    pre = len(rule.per_bar_records)
    assert rule.harvested
    for _ in range(5):
        rule.apply([eur_leg, jpy_leg], 999, idx[-1])
    assert len(rule.per_bar_records) == pre


# ---------------------------------------------------------------------------
# Test 6 — per-leg block widths
# ---------------------------------------------------------------------------


def test_per_leg_block_widths_2_legs():
    """2-leg basket emits 16 leg_<i>_* columns (8 per leg)."""
    n = 5
    eur = np.full(n, 1.10001)
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    record = rule.per_bar_records[0]
    leg_cols = [k for k in record.keys() if k.startswith("leg_")]
    assert len(leg_cols) == 16, f"expected 16 leg cols; got {len(leg_cols)}: {sorted(leg_cols)}"
    assert any(k.startswith("leg_0_") for k in leg_cols)
    assert any(k.startswith("leg_1_") for k in leg_cols)
    assert all(not k.startswith("leg_2_") for k in leg_cols)
    # Each leg has 8 suffixes
    leg_0_cols = [k for k in leg_cols if k.startswith("leg_0_")]
    leg_1_cols = [k for k in leg_cols if k.startswith("leg_1_")]
    assert len(leg_0_cols) == 8
    assert len(leg_1_cols) == 8


# ---------------------------------------------------------------------------
# Test 7 — peak_equity monotonic non-decreasing
# ---------------------------------------------------------------------------


def test_peak_equity_monotonic_nondecreasing():
    """peak_equity_usd never decreases across the record stream."""
    n = 25
    eur = 1.100 + 0.001 * np.sin(np.linspace(0, 4 * np.pi, n))
    jpy = 150.0 + 0.5 * np.cos(np.linspace(0, 4 * np.pi, n))
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    peaks = [r["peak_equity_usd"] for r in rule.per_bar_records]
    for prev, curr in zip(peaks, peaks[1:]):
        assert curr >= prev, f"peak_equity decreased: {prev} -> {curr}"


# ---------------------------------------------------------------------------
# Test 8 — dd_from_peak non-positive
# ---------------------------------------------------------------------------


def test_dd_from_peak_nonpositive():
    """dd_from_peak_usd <= 0 on every record (drawdown-from-peak by definition)."""
    n = 30
    eur = 1.100 + 0.005 * np.sin(np.linspace(0, 2 * np.pi, n))
    jpy = 150.0 + np.cos(np.linspace(0, 2 * np.pi, n))
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    for rec in rule.per_bar_records:
        assert rec["dd_from_peak_usd"] <= 0, f"positive dd: {rec['dd_from_peak_usd']}"
        assert rec["dd_from_peak_pct"] <= 0, f"positive dd %: {rec['dd_from_peak_pct']}"


# ---------------------------------------------------------------------------
# Bonus — every record has all 35 fixed-schema columns
# ---------------------------------------------------------------------------


def test_record_has_all_35_fixed_columns():
    """Every record carries the full Block A-G fixed schema (35 columns)."""
    from tools.basket_report import _FIXED_LEDGER_COLUMNS
    assert len(_FIXED_LEDGER_COLUMNS) == 35

    n = 10
    eur = np.full(n, 1.10001)
    jpy = np.full(n, 150.0)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule()
    _drive_rule(rule, eur_leg, jpy_leg, idx)
    for rec in rule.per_bar_records:
        missing = set(_FIXED_LEDGER_COLUMNS) - set(rec.keys())
        assert not missing, f"record missing fixed cols: {missing}"


def test_equity_invariant_at_recycle_bars():
    """At recycle event bars (and every other bar), equity = stake + realized + floating.

    This is the parity-check regression test (2026-05-16): before the fix,
    the emitter recorded PRE-recycle floating but POST-recycle realized at
    event bars, breaking the equity invariant. Fix restores consistency by
    recomputing floating after state mutation.
    """
    n = 25
    # Construct a scenario with multiple recycles
    eur = np.linspace(1.100, 1.140, n)
    jpy = np.linspace(150.0, 148.0, n)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = _default_rule(trigger_usd=10.0)
    _drive_rule(rule, eur_leg, jpy_leg, idx)

    stake = rule.starting_equity
    recycle_bars = [r for r in rule.per_bar_records if r["recycle_executed"]]
    assert len(recycle_bars) >= 1, "test fixture didn't trigger any recycles"

    # Every record must satisfy equity = stake + realized + floating
    for rec in rule.per_bar_records:
        computed = stake + rec["realized_total_usd"] + rec["floating_total_usd"]
        recorded = rec["equity_total_usd"]
        delta = abs(computed - recorded)
        assert delta < 1e-6, (
            f"equity invariant violated at bar {rec['bar_index']} "
            f"(recycle={rec['recycle_executed']}): "
            f"recorded={recorded}, "
            f"computed (stake+realized+floating)={computed}, "
            f"delta={delta}"
        )

    # Specifically at recycle bars: winner's per-leg floating must be 0
    # (winner's avg_entry was reset to current close → PnL = 0).
    for rec in recycle_bars:
        widx = rec["winner_leg_idx"]
        if widx is None:
            continue
        wf = rec[f"leg_{int(widx)}_floating_usd"]
        assert abs(wf) < 1e-6, (
            f"winner leg floating != 0 at recycle bar (post-reset should be 0): "
            f"bar={rec['bar_index']}, winner_leg_idx={widx}, "
            f"leg_{int(widx)}_floating_usd={wf}"
        )
