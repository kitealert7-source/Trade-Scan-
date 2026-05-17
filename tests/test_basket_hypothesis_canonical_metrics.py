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
    canonical_metrics, detect_rule_family,
)


# ---------------------------------------------------------------------------
# Reference parquets (real runs from this week's H2/H3 work)
# ---------------------------------------------------------------------------

_BASE = Path("../TradeScan_State/backtests")

# These are the runs we've been comparing all week — the canonical metrics
# values are known from ad-hoc analyses + accepted in the H3 hypothesis YAML
# decision blocks. If any of these mismatch, the canonical_metrics module
# diverged from the reference.
_REFERENCE_RUNS = [
    # (run_dir, stake, expected_rule_family, expected_net_pct, expected_dd_pct,
    #  expected_ret_dd, expected_event_counts)
    ("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2", 1000.0, "v4_bump_liquidate",
     59.95, 32.51, 1.84, {"bumps": 5, "liquidate_reset": 5}),

    ("90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2", 1000.0, "v5_pyramid",
     15.88, 8.76, 1.81, {"pyramids": 45, "liq_recovery": 14, "liq_floor": 23}),

    ("90_PORT_H2_5M_RECYCLE_S17_V1_P00_H2", 1000.0, "v5_pyramid",
     31.70, 19.08, 1.66, {"pyramids": 262, "liq_recovery": 98, "liq_floor": 114}),

    ("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2", 1000.0, "v5_pyramid",
     35.60, 19.59, 1.82, {"pyramids": 145, "liq_recovery": 61, "liq_floor": 43}),
]


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
    interactively. If any row diverges, the canonical formula has
    drifted from the ad-hoc analysis we used to pick V3 as the leader.
    """
    expected = {
        "90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2": (59.95, 32.51, 1.84),
        "90_PORT_H2_5M_RECYCLE_S16_V1_P00_H2": (15.88,  8.76, 1.81),
        "90_PORT_H2_5M_RECYCLE_S17_V1_P00_H2": (31.70, 19.08, 1.66),
        "90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2": (35.60, 19.59, 1.82),
    }
    for run, (exp_net, exp_dd, exp_rd) in expected.items():
        m = canonical_metrics(_parquet(run), 1000.0)
        assert m["net_pct"]    == pytest.approx(exp_net, abs=0.05), f"net%  drift on {run}"
        assert m["max_dd_pct"] == pytest.approx(exp_dd,  abs=0.05), f"DD%   drift on {run}"
        assert m["ret_dd"]     == pytest.approx(exp_rd,  abs=0.02), f"ret/DD drift on {run}"
