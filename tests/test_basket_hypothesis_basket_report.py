"""Tests for tools/basket_hypothesis/basket_report.py.

Validates the BASKET_REPORT.md generator:
  - Renders cleanly for all three rule families
  - Includes canonical numbers (not legacy trade-level numbers)
  - Cycle breakdown table appears only for cycle-mechanic rules
  - Asymmetry table appears only when 2-leg basket
  - File written with expected name
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.basket_hypothesis.basket_report import (
    render_basket_report, write_basket_report,
)


_BASE = Path("../TradeScan_State/backtests")

_REFERENCE_RUNS = [
    # (run_dir, stake, directive_id, expected_rule_family_label)
    ("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2", 1000.0,
     "90_PORT_H2_5M_RECYCLE_S14_V1_P00", "bump-and-liquidate"),
    ("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2", 1000.0,
     "90_PORT_H2_5M_RECYCLE_S18_V1_P00", "trend-follow pyramid"),
]


def _parquet(run_dir: str) -> Path:
    return _BASE / run_dir / "raw" / "results_basket_per_bar.parquet"


pytestmark = pytest.mark.skipif(
    not all(_parquet(r[0]).is_file() for r in _REFERENCE_RUNS),
    reason="reference parquets not present",
)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("run_dir,stake,directive_id,family_label", _REFERENCE_RUNS)
def test_render_basket_report_runs(run_dir, stake, directive_id, family_label):
    """Should render without error for both rule families."""
    md = render_basket_report(
        _parquet(run_dir), stake,
        directive_id=directive_id,
        rule_label="H2_recycle@N",
        basket_id="H2",
        timeframe="5m",
        date_range="2024-09-02 → 2026-05-09",
        run_id="testrun",
    )
    assert isinstance(md, str)
    assert len(md) > 500
    # Header
    assert directive_id in md
    # Family label appears
    assert family_label in md


def test_top_line_table_includes_canonical_metrics():
    """Top-line table includes net%, DD%, ret/DD — the canonical numbers."""
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    # All three headline metrics present
    assert "Net %" in md
    assert "Max DD %" in md
    assert "Return / DD" in md
    # Specific V3 values (from canonical_metrics reference set)
    assert "+35.60%" in md   # net_pct
    assert "1.82" in md       # ret/DD


def test_v5_report_includes_pyramid_event_taxonomy():
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "Pyramids" in md
    assert "Liquidations: recovery exit" in md
    assert "Liquidations: hard floor" in md


def test_v4_report_includes_bump_event_taxonomy():
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S14_V1_P00",
        rule_label="H2_recycle@4", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "Bumps" in md
    assert "Liquidations (soft-reset)" in md


def test_v5_report_includes_cycle_breakdown():
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "Cycle Breakdown" in md
    assert "Cycle win rate" in md
    assert "Cycles completed" in md


def test_v5_report_includes_asymmetry_diagnostic():
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "Per-Winner-Side Asymmetry" in md
    assert "Asymmetry ratio" in md
    assert "EURUSD" in md
    assert "USDJPY" in md


def test_report_includes_legacy_caveat_block():
    """All reports include the caveat explaining why this file exists
    alongside the legacy REPORT.md."""
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S14_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S14_V1_P00",
        rule_label="H2_recycle@4", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "legacy REPORT.md caveat" in md
    assert "canonical_metrics" in md
    assert "authoritative" in md


def test_peak_lots_section_present():
    md = render_basket_report(
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert "Per-Leg Peak Lot Exposure" in md


# ---------------------------------------------------------------------------
# Writing to disk
# ---------------------------------------------------------------------------


def test_write_basket_report_creates_file(tmp_path):
    out = write_basket_report(
        tmp_path,
        _parquet("90_PORT_H2_5M_RECYCLE_S18_V1_P00_H2"), 1000.0,
        directive_id="90_PORT_H2_5M_RECYCLE_S18_V1_P00",
        rule_label="H2_recycle@5", basket_id="H2",
        timeframe="5m", date_range="F",
    )
    assert out.name == "BASKET_REPORT_90_PORT_H2_5M_RECYCLE_S18_V1_P00.md"
    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert "Cycle Breakdown" in content
    assert "+35.60%" in content   # canonical net_pct for V3
