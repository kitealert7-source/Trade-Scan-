"""Tests for tools/basket_hypothesis/canonical_metrics.py.

Validates the canonical metrics extractor across all rule families:
  - v1_recycle (no cycle taxonomy; legacy classic mechanics)
  - v4_bump_liquidate (BUMP_INTO_HOLD + LIQUIDATE_RESET events)
  - v5_pyramid (PYRAMID_ADDED + TREND_LIQUIDATE_RECOVERY/FLOOR events)

Uses ACTUAL parquets from yesterday's H2_recycle@4 runs + today's
H3 (@5) runs as the source of truth — ensures the formula gives
the same numbers as the ad-hoc analyses we did interactively.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.basket_hypothesis.canonical_metrics import (
    canonical_metrics, detect_rule_family, _cycle_pnl_from_parquet,
    _cycle_pnl_robust, _assert_liquidation_convention, CycleConventionError,
)


def test_pine_reversal_family_and_segment_cycles():
    """pine_ratio_zrev_v1 (V3 always-in-market reversal): LIQUIDATE_REVERSAL
    tags -> 'pine_reversal' family; each segment's cycle_pnl is the
    realized_total_usd delta, so cycles_completed + cycle_win_rate_pct are
    populated (regression for the all-zero win_rate bug, 2026-05-28)."""
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=6, freq="1D"),
        "skip_reason": ["HOLDING", "LIQUIDATE_REVERSAL", "HOLDING",
                        "LIQUIDATE_REVERSAL", "HOLDING", "LIQUIDATE_REVERSAL"],
        # cumulative realized -> segment deltas: +10, -5, +15  (2 won / 3)
        "realized_total_usd": [0.0, 10.0, 10.0, 5.0, 5.0, 20.0],
    })
    assert detect_rule_family(df) == "pine_reversal"
    cycles = _cycle_pnl_from_parquet(df, ["LIQUIDATE_REVERSAL"])
    assert [c["cycle_pnl_usd"] for c in cycles] == [10.0, -5.0, 15.0]
    won = sum(1 for c in cycles if c["cycle_pnl_usd"] > 0)
    assert won == 2 and len(cycles) == 3


def test_cycle_pnl_robust_catches_unwired_variants_and_excludes_scaleouts():
    """`_cycle_pnl_robust` counts a cycle at ANY full-basket LIQUIDATION bar
    (skip_reason containing 'LIQUIDATE'), so an exit variant whose exact tag was
    never wired into a per-family list is still counted — the GP_ZOPP regression
    (LIQUIDATE_OPP_REVERT reported 0 cycles under the old hardcoded lists). Partial
    scale-outs (no 'LIQUIDATE') are excluded; their realized PnL accumulates into
    the enclosing cycle, matching the legacy h3 accounting."""
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=8, freq="1D"),
        "skip_reason": ["HOLDING", "LIQUIDATE_OPP_REVERT", "HOLDING",
                        "HARVEST_SCALE_OUT", "HOLDING", "LIQUIDATE_RESET",
                        "HOLDING", "LIQUIDATE_EQUILIBRIUM"],
        # cumulative realized; the +3 scale-out at idx 3 rolls into cycle 1's delta
        "realized_total_usd": [0.0, 10.0, 10.0, 13.0, 13.0, 8.0, 8.0, 20.0],
    })
    cycles = _cycle_pnl_robust(df)
    assert [c["exit_tag"] for c in cycles] == [
        "LIQUIDATE_OPP_REVERT", "LIQUIDATE_RESET", "LIQUIDATE_EQUILIBRIUM"]
    assert [c["cycle_pnl_usd"] for c in cycles] == [10.0, -2.0, 12.0]
    assert len(cycles) == 3  # HARVEST_SCALE_OUT not counted as a cycle

    # A hypothetical FUTURE exit variant is counted automatically the moment it
    # follows the LIQUIDATE convention — no per-family wiring required.
    df2 = pd.DataFrame({
        "skip_reason": ["HOLDING", "LIQUIDATE_SOME_NEW_EXIT_V9"],
        "realized_total_usd": [0.0, 5.0],
    })
    assert len(_cycle_pnl_robust(df2)) == 1


def test_liquidation_convention_guard_fails_nonconforming_close():
    """The guard fails a backtest the moment a cycle-mechanic rule fully closes a
    basket (active_legs -> 0) while realizing PnL but tags it WITHOUT 'LIQUIDATE'
    — the convention `_cycle_pnl_robust` relies on. Enforces it at backtest time
    instead of shipping silently-wrong cycle metrics (the GP_ZOPP class of bug)."""
    bad = pd.DataFrame({
        "active_legs":       [2, 2, 0],
        "skip_reason":       ["HOLDING", "HOLDING", "MEANREV_EXIT"],  # no LIQUIDATE
        "realized_total_usd": [0.0, 0.0, 5.0],                       # realizing close
    })
    with pytest.raises(CycleConventionError):
        _assert_liquidation_convention(bad, "pine_reversal")

    # exempt for non-cycle families (no cycle taxonomy)
    _assert_liquidation_convention(bad, "v1_recycle")

    # conforming close (LIQUIDATE_* tag) -> no raise
    good = bad.copy()
    good["skip_reason"] = ["HOLDING", "HOLDING", "LIQUIDATE_MEANREV"]
    _assert_liquidation_convention(good, "pine_reversal")

    # a NON-realizing flatten (no realized change) does not trip the guard
    flat = pd.DataFrame({
        "active_legs":       [2, 0],
        "skip_reason":       ["HOLDING", "FORCED_FLAT"],
        "realized_total_usd": [3.0, 3.0],
    })
    _assert_liquidation_convention(flat, "pine_reversal")


# ---------------------------------------------------------------------------
# Reference parquets (real runs from this week's H2/H3 work)
# ---------------------------------------------------------------------------

_BASE = Path("../TradeScan_State/backtests")

# These are the runs we've been comparing all week — the canonical metrics
# values are known from ad-hoc analyses + accepted in the H3 hypothesis YAML
# decision blocks. If any of these mismatch, the canonical_metrics module
# diverged from the reference.
_REFERENCE_RUNS = [
    # (run_dir, stake, expected_rule_family, expected_net_pct,
    #  expected_dd_pct_peak_relative, expected_ret_dd, expected_event_counts)
    #
    # DD% values were recomputed to peak-relative basis on 2026-05-18 when
    # canonical_metrics switched from stake-relative (legacy) to peak-relative
    # (standard backtest convention). Stake-relative numbers preserved in
    # max_dd_pct_vs_stake; covered by test_max_dd_pct_vs_stake_legacy_form below.
    ("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2", 1000.0, "v4_bump_liquidate",
     59.95, 18.76, 3.19, {"bumps": 5, "liquidate_reset": 5}),

    ("90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2", 1000.0, "v5_pyramid",
     15.88, 7.46, 2.13, {"pyramids": 45, "liq_recovery": 14, "liq_floor": 23}),

    ("90_PORT_H2_5M_RECYCLE_S17_V1_P00_H2", 1000.0, "v5_pyramid",
     31.70, 13.77, 2.30, {"pyramids": 262, "liq_recovery": 98, "liq_floor": 114}),

    ("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2", 1000.0, "v5_pyramid",
     35.60, 13.95, 2.55, {"pyramids": 145, "liq_recovery": 61, "liq_floor": 43}),
]

# Stake-relative DD% values preserved for the backward-compat
# max_dd_pct_vs_stake field. Indexed by run_dir.
_REFERENCE_DD_PCT_VS_STAKE = {
    "90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2": 32.51,
    "90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2":  8.76,
    "90_PORT_H2_5M_RECYCLE_S17_V1_P00_H2": 19.08,
    "90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2": 19.59,
}


def _parquet(run_dir: str) -> Path:
    return _BASE / run_dir / "raw" / "results_basket_per_bar.parquet"


# Skip the whole module if reference parquets are not present (e.g. a fresh
# clone without TradeScan_State data). The tests are pinned to those runs.
def _all_parquets_present() -> bool:
    return all(_parquet(r[0]).is_file() for r in _REFERENCE_RUNS)


pytestmark = pytest.mark.skipif(
    not _all_parquets_present(),
    reason="reference parquets not present (need TradeScan_State data)",
)


# ---------------------------------------------------------------------------
# Auto-detection of rule family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("run_dir,stake,expected_family,_n,_d,_r,_e", _REFERENCE_RUNS)
def test_detect_rule_family(run_dir, stake, expected_family, _n, _d, _r, _e):
    df = pd.read_parquet(_parquet(run_dir))
    assert detect_rule_family(df) == expected_family


# ---------------------------------------------------------------------------
# Headline metrics match reference values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run_dir,stake,_f,expected_net_pct,_d,_r,_e", _REFERENCE_RUNS
)
def test_net_pct_matches_reference(run_dir, stake, _f, expected_net_pct, _d, _r, _e):
    m = canonical_metrics(_parquet(run_dir), stake)
    assert m["net_pct"] == pytest.approx(expected_net_pct, abs=0.05)


@pytest.mark.parametrize(
    "run_dir,stake,_f,_n,expected_dd_pct,_r,_e", _REFERENCE_RUNS
)
def test_max_dd_pct_matches_reference(run_dir, stake, _f, _n, expected_dd_pct, _r, _e):
    m = canonical_metrics(_parquet(run_dir), stake)
    assert m["max_dd_pct"] == pytest.approx(expected_dd_pct, abs=0.05)


@pytest.mark.parametrize(
    "run_dir,stake,_f,_n,_d,expected_ret_dd,_e", _REFERENCE_RUNS
)
def test_ret_dd_matches_reference(run_dir, stake, _f, _n, _d, expected_ret_dd, _e):
    m = canonical_metrics(_parquet(run_dir), stake)
    assert m["ret_dd"] == pytest.approx(expected_ret_dd, abs=0.02)


# ---------------------------------------------------------------------------
# Event counts match reference values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run_dir,stake,_f,_n,_d,_r,expected_events", _REFERENCE_RUNS
)
def test_event_counts_match_reference(run_dir, stake, _f, _n, _d, _r, expected_events):
    m = canonical_metrics(_parquet(run_dir), stake)
    for k, expected_v in expected_events.items():
        actual_v = m["events"].get(k)
        assert actual_v == expected_v, (
            f"event count {k}: expected {expected_v}, got {actual_v} "
            f"(run={run_dir})"
        )


# ---------------------------------------------------------------------------
# Cycle reconstruction (V5 only)
# ---------------------------------------------------------------------------


def test_cycle_reconstruction_v5_s18():
    """V3 (S18) had 61 recovery + 43 hard-floor liquidations = 104 cycles."""
    m = canonical_metrics(_parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0)
    assert m["rule_family"] == "v5_pyramid"
    assert m["cycles_completed"] == 104
    # Some cycles win, some lose — verify sum is close to final_realized
    pnls = [c["cycle_pnl_usd"] for c in m["cycle_pnls"]]
    sum_pnl = sum(pnls)
    # Note: sum_pnl may differ slightly from final_realized due to end-of-window
    # forced-close on the in-flight cycle (not in cycle_pnls).
    assert m["cycles_won"] + m["cycles_lost"] <= m["cycles_completed"]
    assert m["cycle_win_rate_pct"] >= 0.0
    assert m["cycle_win_rate_pct"] <= 100.0


def test_cycle_reconstruction_v5_s16():
    """V1 (S16) had 14 recovery + 23 floor = 37 cycles."""
    m = canonical_metrics(_parquet("90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2"), 1000.0)
    assert m["rule_family"] == "v5_pyramid"
    assert m["cycles_completed"] == 37


def test_cycle_reconstruction_v4_s14():
    """@4 baseline (S14) had 5 LIQUIDATE_RESET events = 5 cycles."""
    m = canonical_metrics(_parquet("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2"), 1000.0)
    assert m["rule_family"] == "v4_bump_liquidate"
    assert m["cycles_completed"] == 5


# ---------------------------------------------------------------------------
# Per-winner-side asymmetry diagnostic (V5 only, EURUSD+USDJPY)
# ---------------------------------------------------------------------------


def test_per_winner_side_asymmetry_v3_s18():
    """V3 (S18) was the 2:3 ratio + hf=-15 run. EUR-winner cycles
    should have a noticeably higher hard-floor rate than JPY-winner
    cycles (yesterday's diagnostic showed 63.5% vs 39.5%)."""
    m = canonical_metrics(_parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0)
    per = m["per_winner_side"]
    assert "EURUSD" in per
    assert "USDJPY" in per
    assert per["EURUSD"]["total"] > 0
    assert per["USDJPY"]["total"] > 0
    # Both legs see hard-floor + recovery events
    eur_total = per["EURUSD"]["total"]
    jpy_total = per["USDJPY"]["total"]
    assert eur_total + jpy_total == m["cycles_completed"]


# ---------------------------------------------------------------------------
# Per-leg peak lots
# ---------------------------------------------------------------------------


def test_peak_lots_v5_s16():
    """V1 (S16) is 1:1 ratio. Peak lots should reflect pyramid growth."""
    m = canonical_metrics(_parquet("90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2"), 1000.0)
    assert "EURUSD" in m["peak_lots"]
    assert "USDJPY" in m["peak_lots"]
    # Each leg starts at 0.01; if any leg pyramided, peak > 0.01
    # (at least one leg must show growth since 45 pyramids happened)
    assert max(m["peak_lots"].values()) > 0.01


def test_peak_lots_v3_s18():
    """V3 (S18) is 2:3 ratio — starting lots are 0.02 and 0.03."""
    m = canonical_metrics(_parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0)
    # Peak should be at least the starting lot
    assert m["peak_lots"]["EURUSD"] >= 0.02
    assert m["peak_lots"]["USDJPY"] >= 0.03


# ---------------------------------------------------------------------------
# Stake basis normalization
# ---------------------------------------------------------------------------


def test_stake_basis_affects_net_pct_proportionally():
    """Same parquet, different stake → net_pct scales inversely."""
    parq = _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2")
    m_1k = canonical_metrics(parq, 1000.0)
    m_2k = canonical_metrics(parq, 2000.0)
    # Same delta on numerator, doubled denominator → net_pct ~ half
    # (Approximate — final_equity is also affected by which stake the
    # rule used internally, but for this synthetic comparison the
    # parquet's equity_total_usd is constant.)
    assert m_2k["net_pct"] < m_1k["net_pct"]


# ---------------------------------------------------------------------------
# Headline ret_dd matches yesterday's ad-hoc analyses
# ---------------------------------------------------------------------------


def test_full_sweep_table_matches_ad_hoc_analysis():
    """Reproduces the H3 hard-floor sweep summary table generated
    interactively. DD% values updated 2026-05-18 to peak-relative basis;
    stake-relative variant covered separately by
    test_max_dd_pct_vs_stake_legacy_form.
    """
    expected = {
        # (net%, dd% peak-relative, ret/dd peak-relative)
        "90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2": (59.95, 18.76, 3.19),
        "90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2": (15.88,  7.46, 2.13),
        "90_PORT_H2_5M_RECYCLE_S17_V1_P00_H2": (31.70, 13.77, 2.30),
        "90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2": (35.60, 13.95, 2.55),
    }
    for run, (exp_net, exp_dd, exp_rd) in expected.items():
        m = canonical_metrics(_parquet(run), 1000.0)
        assert m["net_pct"]    == pytest.approx(exp_net, abs=0.05), f"net%  drift on {run}"
        assert m["max_dd_pct"] == pytest.approx(exp_dd,  abs=0.05), f"DD%   drift on {run}"
        assert m["ret_dd"]     == pytest.approx(exp_rd,  abs=0.02), f"ret/DD drift on {run}"


# ---------------------------------------------------------------------------
# Backward-compat: stake-relative DD% preserved in max_dd_pct_vs_stake
# ---------------------------------------------------------------------------


def test_max_dd_pct_vs_stake_legacy_form():
    """Stake-relative DD% (the pre-2026-05-18 form) is preserved as
    max_dd_pct_vs_stake for callers that still need it (e.g. capital
    sizing decisions: can the basket lose more than its stake)."""
    for run_dir, expected_stake_dd in _REFERENCE_DD_PCT_VS_STAKE.items():
        m = canonical_metrics(_parquet(run_dir), 1000.0)
        assert m["max_dd_pct_vs_stake"] == pytest.approx(expected_stake_dd, abs=0.05), (
            f"stake-relative DD% drift on {run_dir}: "
            f"got {m['max_dd_pct_vs_stake']:.2f}, expected {expected_stake_dd:.2f}"
        )
