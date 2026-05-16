"""Unit tests for the 1.3.0-basket per-bar ledger emit in H2RecycleRuleV3.

Mirrors tests/test_h2_recycle_ledger_emit.py (the @1 version) — same gates,
adapted for cross-pair PnL math via _usd_value_of_ccy. Uses AUDJPY + EURGBP
as the canonical cross-pair test basket (4 distinct currencies, no-shared-
currency rule satisfied).

Phase B (2026-05-16): @3 opted into the per_bar_records contract. These
tests pin the contract so future refactors can't regress it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg
from tools.recycle_rules.h2_recycle_v3 import H2RecycleRuleV3
from engine_abi.v1_5_9 import BarState


# ---------------------------------------------------------------------------
# Fixtures — AUDJPY + EURGBP cross-pair basket
# ---------------------------------------------------------------------------


def _make_cross_basket(audjpy, eurgbp, comp, *, audjpy_lot=0.01, eurgbp_lot=0.01,
                       audusd=0.66, gbpusd=1.27, usdjpy=150.0, eurusd=1.10):
    """Build a 2-leg cross-pair basket with USD reference rates joined.

    AUDJPY long + EURGBP long — currencies: AUD, JPY, EUR, GBP (4 distinct).
    """
    n = len(audjpy)
    assert len(eurgbp) == n == len(comp)
    idx = pd.date_range("2024-09-02 00:00:00", periods=n, freq="5min")

    # Reference rates broadcast across all bars (could vary, but constant is fine for unit tests)
    audusd_arr = np.full(n, audusd)
    gbpusd_arr = np.full(n, gbpusd)
    usdjpy_arr = np.full(n, usdjpy)
    eurusd_arr = np.full(n, eurusd)

    audjpy_df = pd.DataFrame({
        "open": audjpy, "high": audjpy, "low": audjpy, "close": audjpy,
        "compression_5d": comp,
        "usd_ref_AUDUSD_close": audusd_arr,
        "usd_ref_USDJPY_close": usdjpy_arr,
        "usd_ref_EURUSD_close": eurusd_arr,
        "usd_ref_GBPUSD_close": gbpusd_arr,
    }, index=idx)
    eurgbp_df = pd.DataFrame({
        "open": eurgbp, "high": eurgbp, "low": eurgbp, "close": eurgbp,
        "compression_5d": comp,
        "usd_ref_AUDUSD_close": audusd_arr,
        "usd_ref_USDJPY_close": usdjpy_arr,
        "usd_ref_EURUSD_close": eurusd_arr,
        "usd_ref_GBPUSD_close": gbpusd_arr,
    }, index=idx)

    audjpy_leg = BasketLeg("AUDJPY", lot=audjpy_lot, direction=+1, df=audjpy_df, strategy=None)  # type: ignore[arg-type]
    eurgbp_leg = BasketLeg("EURGBP", lot=eurgbp_lot, direction=+1, df=eurgbp_df, strategy=None)  # type: ignore[arg-type]
    for leg, prices in [(audjpy_leg, audjpy), (eurgbp_leg, eurgbp)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return audjpy_leg, eurgbp_leg, idx


def _drive_rule(rule, audjpy_leg, eurgbp_leg, idx, *, start=0):
    for i in range(start, len(idx)):
        rule.apply([audjpy_leg, eurgbp_leg], i, idx[i])


def _default_rule(**overrides):
    params = dict(
        trigger_usd=10.0,
        add_lot=0.01,
        starting_equity=1000.0,
        harvest_target_usd=2000.0,
        dd_freeze_frac=0.10,
        margin_freeze_frac=0.15,
        leverage=1000.0,
        factor_column="compression_5d",
        factor_min=-999.0,  # ungated by default (matches S06 / Option A baseline)
        run_id="test_run_v3",
        directive_id="test_directive_v3",
        basket_id="H2",
    )
    params.update(overrides)
    return H2RecycleRuleV3(**params)


# ---------------------------------------------------------------------------
# Test 1 — per_bar_records populated with identity threading
# ---------------------------------------------------------------------------


def test_per_bar_records_populated_v3():
    n = 30
    audjpy = np.full(n, 99.0)
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    assert len(rule.per_bar_records) == n
    for rec in rule.per_bar_records:
        assert rec["directive_id"] == "test_directive_v3"
        assert rec["basket_id"] == "H2"
        assert rec["run_id"] == "test_run_v3"


# ---------------------------------------------------------------------------
# Test 2 — schema conformance (Block A-G columns present)
# ---------------------------------------------------------------------------


def test_schema_conformance_v3():
    n = 5
    audjpy = np.full(n, 99.0)
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    rec = rule.per_bar_records[0]
    # Block A
    for k in ["timestamp", "directive_id", "basket_id", "bar_index", "run_id"]:
        assert k in rec
    # Block B
    for k in ["floating_total_usd", "realized_total_usd", "equity_total_usd",
              "peak_equity_usd", "dd_from_peak_usd", "dd_from_peak_pct"]:
        assert k in rec
    # Block C
    for k in ["margin_used_usd", "free_margin_usd", "margin_level_pct",
              "notional_total_usd", "leverage_effective"]:
        assert k in rec
    # Block D
    for k in ["dd_freeze_active", "margin_freeze_active", "regime_gate_blocked",
              "recycle_attempted", "recycle_executed", "harvest_triggered",
              "engine_paused", "skip_reason"]:
        assert k in rec
    # Block E
    for k in ["active_legs", "total_lot", "largest_leg_lot", "smallest_leg_lot"]:
        assert k in rec
    # Block F (per-leg, wide format, 8 cols × 2 legs)
    for i in [0, 1]:
        for col in ["symbol", "side", "lot", "avg_entry", "mark",
                    "floating_usd", "margin_usd", "notional_usd"]:
            assert f"leg_{i}_{col}" in rec
    # Block G
    for k in ["recycle_count", "bars_since_last_recycle",
              "bars_since_last_harvest", "gate_factor_value", "gate_factor_name",
              "winner_leg_idx", "loser_leg_idx"]:
        assert k in rec


# ---------------------------------------------------------------------------
# Test 3 — skip_reason coverage (each early-return path)
# ---------------------------------------------------------------------------


def test_skip_reason_no_winner_v3():
    n = 20
    audjpy = np.full(n, 99.0)
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "NO_WINNER" in reasons


def test_skip_reason_dd_freeze_v3():
    """Strong adverse JPY move → AUDJPY long deeply negative → dd_breach.

    Note: cross-pair PnL math reduces $-per-pip — at usdjpy=150 on 0.01 lot,
    1 JPY pip = $0.067, so need ~15 JPY drop to generate $100 floating loss
    (10% of $1k stake). Use a 30 JPY drop to be safely past threshold.
    """
    n = 20
    audjpy = np.linspace(99.0, 70.0, n)   # 29 JPY drop → ~$193 floating loss at usdjpy=150
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "DD_FREEZE" in reasons, f"got reasons: {reasons}"
    assert rule.summary_stats["dd_freeze_count"] >= 1


def test_skip_reason_regime_gate_v3():
    """Factor below min and Gate=10 → REGIME_GATE."""
    n = 20
    audjpy = np.full(n, 99.0)
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 5.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule(factor_min=10.0)
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    reasons = {rec["skip_reason"] for rec in rule.per_bar_records}
    assert "REGIME_GATE" in reasons
    assert rule.summary_stats["regime_freeze_count"] >= 1


def test_skip_reason_recycle_executed_v3():
    """AUDJPY rises strongly → winner; EURGBP unchanged but negative-floating won't fire;
    so instead use AUDJPY winner + EURGBP losing scenario."""
    n = 30
    # AUDJPY rises (winner), EURGBP drops (loser)
    audjpy = np.concatenate([np.full(5, 99.0), np.linspace(99.0, 100.5, 25)])
    eurgbp = np.concatenate([np.full(5, 0.866), np.linspace(0.866, 0.855, 25)])
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    # At least one bar should have recycle_executed=True with skip_reason="NONE"
    executed = [rec for rec in rule.per_bar_records if rec["recycle_executed"]]
    assert len(executed) >= 1, f"no recycle executed; reasons: {set(r['skip_reason'] for r in rule.per_bar_records)}"
    for rec in executed:
        assert rec["skip_reason"] == "NONE"


# ---------------------------------------------------------------------------
# Test 4 — equity invariant at recycle bars (regression test for state-capture)
# ---------------------------------------------------------------------------


def test_equity_invariant_at_recycle_bars_v3():
    """Post-state recompute preserves equity = stake + realized + floating on recycle bars."""
    n = 50
    audjpy = np.concatenate([np.full(5, 99.0), np.linspace(99.0, 101.0, 45)])
    eurgbp = np.concatenate([np.full(5, 0.866), np.linspace(0.866, 0.852, 45)])
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    for rec in rule.per_bar_records:
        eq = rec["equity_total_usd"]
        invariant = rule.starting_equity + rec["realized_total_usd"] + rec["floating_total_usd"]
        assert abs(eq - invariant) < 0.01, (
            f"equity invariant violated at bar {rec['bar_index']}: "
            f"eq={eq}, stake+realized+floating={invariant}"
        )


# ---------------------------------------------------------------------------
# Test 5 — cross-pair PnL: per-leg floating uses USD ref-pair conversion
# ---------------------------------------------------------------------------


def test_cross_pair_floating_uses_usd_conversion():
    """For AUDJPY at usdjpy=150, +1 JPY pip on 0.01 lot ≈ $0.067 (not $1)."""
    n = 5
    # Move AUDJPY by 0.01 JPY = 1 pip in quote ccy
    audjpy = np.array([99.0, 99.01, 99.02, 99.03, 99.04])
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp, usdjpy=150.0)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    # Floating on AUDJPY at bar 4: 0.01 lot × 100k units × (99.04 - 99.00) JPY = 40 JPY
    # USD value: 40 / 150 = $0.267
    last_rec = rule.per_bar_records[-1]
    audjpy_float = last_rec["leg_0_floating_usd"]
    expected = (99.04 - 99.0) * 0.01 * 100_000 / 150.0  # ~ 0.267
    assert abs(audjpy_float - expected) < 0.05, (
        f"cross-pair PnL math wrong: got {audjpy_float}, expected ~{expected}"
    )


def test_cross_pair_margin_uses_usd_conversion():
    """For AUDJPY at audusd=0.66, 0.01 lot margin = 1000 AUD × 0.66 / 1000 ≈ $0.66."""
    n = 3
    audjpy = np.full(n, 99.0)
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp, audusd=0.66, eurusd=1.10)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    rec = rule.per_bar_records[0]
    audjpy_margin = rec["leg_0_margin_usd"]
    expected_audjpy = 0.01 * 100_000 * 0.66 / 1000  # ~ $0.66
    assert abs(audjpy_margin - expected_audjpy) < 0.05
    eurgbp_margin = rec["leg_1_margin_usd"]
    expected_eurgbp = 0.01 * 100_000 * 1.10 / 1000  # ~ $1.10
    assert abs(eurgbp_margin - expected_eurgbp) < 0.05


# ---------------------------------------------------------------------------
# Test 6 — summary_stats accumulator behavior
# ---------------------------------------------------------------------------


def test_summary_stats_peak_floating_dd_tracks_min():
    """peak_floating_dd_usd is the running min of dd_from_peak_usd (most negative)."""
    n = 30
    audjpy = np.concatenate([np.linspace(99.0, 97.0, 15), np.linspace(97.0, 99.5, 15)])
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    stats = rule.summary_stats
    # The accumulator should match the actual min over records
    actual_min = min(rec["dd_from_peak_usd"] for rec in rule.per_bar_records)
    assert abs(stats["peak_floating_dd_usd"] - actual_min) < 0.01


def test_summary_stats_peak_lots_tracks_max():
    """peak_lots dict tracks max(lot) per symbol observed."""
    n = 50
    # Setup that triggers recycles → loser grows lots
    audjpy = np.concatenate([np.full(5, 99.0), np.linspace(99.0, 101.0, 45)])
    eurgbp = np.concatenate([np.full(5, 0.866), np.linspace(0.866, 0.850, 45)])
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    peak_lots = rule.summary_stats["peak_lots"]
    # Both symbols should be in peak_lots and ≥ their starting lot
    assert peak_lots.get("AUDJPY", 0) >= 0.01
    assert peak_lots.get("EURGBP", 0) >= 0.01


# ---------------------------------------------------------------------------
# Test 7 — identity threading default empty doesn't crash
# ---------------------------------------------------------------------------


def test_runs_without_identity_threading():
    """Backward compat: rule still works if run_id/directive_id/basket_id are empty."""
    n = 5
    audjpy = np.full(n, 99.0)
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = H2RecycleRuleV3(
        trigger_usd=10.0, add_lot=0.01, starting_equity=1000.0,
        harvest_target_usd=2000.0, dd_freeze_frac=0.10, margin_freeze_frac=0.15,
        leverage=1000.0, factor_min=-999.0,
        # NO run_id/directive_id/basket_id
    )
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    assert len(rule.per_bar_records) == n
    for rec in rule.per_bar_records:
        assert rec["directive_id"] == ""
        assert rec["run_id"] == ""


# ---------------------------------------------------------------------------
# Test 8 — harvest_triggered path emits a record + finalizes summary_stats
# ---------------------------------------------------------------------------


def test_harvest_triggers_record_and_finalize():
    """Use bigger lots + dramatic price rise so we cross harvest target.

    With 0.10 lot AUDJPY at usdjpy=150, +10 JPY rise = $666 floating PnL,
    well past the $1010 harvest target on $1000 stake.
    """
    n = 50
    # Both legs rise sharply (engineered for a big positive PnL spike at the harvest target).
    audjpy = np.concatenate([np.full(5, 99.0), np.linspace(99.0, 110.0, 45)])
    eurgbp = np.full(n, 0.866)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(
        audjpy, eurgbp, comp, audjpy_lot=0.10, eurgbp_lot=0.10
    )
    # Lower harvest target to ensure we exit
    rule = _default_rule(harvest_target_usd=1010.0)
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    # Should have at least one harvest_triggered=True bar
    harvest_recs = [rec for rec in rule.per_bar_records if rec["harvest_triggered"]]
    assert len(harvest_recs) == 1, f"expected 1 harvest, got {len(harvest_recs)}"
    # summary_stats finalized
    stats = rule.summary_stats
    assert stats["final_pnl_usd"] is not None
    assert stats["harvest_bar_index"] is not None
    assert stats["harvest_bar_ts"] is not None
    assert stats["harvest_reason"] == "TARGET"


# ---------------------------------------------------------------------------
# Test 9 — leg_X_floating_usd sum equals floating_total_usd
# ---------------------------------------------------------------------------


def test_per_leg_floating_sums_to_basket_total():
    """leg_0_floating_usd + leg_1_floating_usd == floating_total_usd at every bar."""
    n = 25
    audjpy = np.linspace(99.0, 100.0, n)
    eurgbp = np.linspace(0.866, 0.860, n)
    comp = np.full(n, 15.0)
    audjpy_leg, eurgbp_leg, idx = _make_cross_basket(audjpy, eurgbp, comp)
    rule = _default_rule()
    _drive_rule(rule, audjpy_leg, eurgbp_leg, idx)
    for rec in rule.per_bar_records:
        per_leg_sum = rec["leg_0_floating_usd"] + rec["leg_1_floating_usd"]
        assert abs(per_leg_sum - rec["floating_total_usd"]) < 0.01, (
            f"per-leg sum mismatch at bar {rec['bar_index']}: "
            f"sum={per_leg_sum}, total={rec['floating_total_usd']}"
        )
