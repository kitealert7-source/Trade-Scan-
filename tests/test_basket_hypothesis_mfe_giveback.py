"""Tests for tools/basket_hypothesis/mfe_giveback.py.

Validates the per-cycle MFE / give-back analytics:
  - Returns the expected dict shape (cycles, summary, by_exit_tag,
    profitable/losing segments, histogram, capture_rate).
  - Aggregate identity: Σ exit_floating + Σ give_back == Σ MFE (clipped @ 0).
  - Works for both cycle-mechanic rule families that emit LIQUIDATE_* tags
    (h3_spread present on the PAIRX runs; v4/v5 on the H2 reference runs).
  - Renders cleanly into BASKET_REPORT.md via render_basket_report.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from tools.basket_hypothesis.basket_report import render_basket_report
from tools.basket_hypothesis.mfe_giveback import compute_mfe_giveback


_BASE = Path("../TradeScan_State/backtests")

# Reference runs span all three cycle-mechanic families:
#  - V5 pyramid (TREND_LIQUIDATE_*),
#  - V4 bump-and-liquidate (LIQUIDATE_RESET),
#  - H3_spread@1 PAIRX BEAR P00 (LIQUIDATE_TIME/ADVERSE/REVERSE).
_RUNS = [
    ("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2",         "v4_bump_liquidate"),
    ("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2",         "v5_pyramid"),
    ("90_PORT_EURUSDUSDJPY_5M_PAIRX_S01_V1_P00_EURUSDUSDJPYBEAR", "h3_spread"),
]


def _parquet(run_dir: str) -> Path:
    return _BASE / run_dir / "raw" / "results_basket_per_bar.parquet"


pytestmark = pytest.mark.skipif(
    not all(_parquet(r[0]).is_file() for r in _RUNS),
    reason="reference parquets not present",
)


@pytest.mark.parametrize("run_dir,expected_family", _RUNS)
def test_compute_mfe_giveback_shape(run_dir, expected_family):
    """Returns expected top-level keys and detects the correct rule family."""
    out = compute_mfe_giveback(_parquet(run_dir))
    assert out["rule_family"] == expected_family
    for k in ("cycles", "summary", "by_exit_tag",
              "profitable", "losing",
              "giveback_pct_histogram", "capture_rate_pct"):
        assert k in out, f"missing key: {k}"
    assert isinstance(out["cycles"], list)
    assert len(out["cycles"]) > 0, "reference runs all have completed cycles"


@pytest.mark.parametrize("run_dir,expected_family", _RUNS)
def test_per_cycle_giveback_identity(run_dir, expected_family):
    """For every cycle: give_back_usd == mfe - exit_floating exactly."""
    out = compute_mfe_giveback(_parquet(run_dir))
    for c in out["cycles"]:
        assert math.isclose(
            c["give_back_usd"], c["mfe"] - c["exit_floating"], abs_tol=1e-6
        )
        # bars_held cannot be negative and entry <= exit
        assert c["bars_held"] >= 0
        assert c["entry_idx"] <= c["exit_idx"]


@pytest.mark.parametrize("run_dir,expected_family", _RUNS)
def test_aggregate_capture_rate_identity(run_dir, expected_family):
    """Aggregate: capture_rate_pct == total_exit / total_mfe * 100 (when MFE>0)."""
    out = compute_mfe_giveback(_parquet(run_dir))
    s = out["summary"]
    total_mfe = s["total_mfe_usd"]
    total_exit = s["total_exit_floating"]
    if total_mfe > 0:
        expected = total_exit / total_mfe * 100.0
        assert math.isclose(out["capture_rate_pct"], expected, abs_tol=1e-6)
    # total_giveback = total_mfe - total_exit
    assert math.isclose(
        s["total_giveback_usd"], total_mfe - total_exit, abs_tol=1e-6
    )


def test_h3_spread_run_includes_per_exit_breakdown():
    """The h3_spread PAIRX BEAR P00 has 3 distinct LIQUIDATE_* tags;
    by_exit_tag should surface them with non-zero counts."""
    out = compute_mfe_giveback(
        _parquet("90_PORT_EURUSDUSDJPY_5M_PAIRX_S01_V1_P00_EURUSDUSDJPYBEAR")
    )
    tags = set(out["by_exit_tag"].keys())
    # P00 (-$2 stop) is mostly adverse exits but should have at least one
    # reverse-cross + time-stop too.
    assert "LIQUIDATE_ADVERSE_STOP" in tags
    for tag in tags:
        d = out["by_exit_tag"][tag]
        assert d["n"] > 0


def test_render_basket_report_includes_mfe_section():
    """The MFE section appears in BASKET_REPORT.md when cycles exist."""
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "Cycle MFE / Give-back" in md
    assert "Aggregate capture rate" in md
    assert "Total unrealized peak" in md
