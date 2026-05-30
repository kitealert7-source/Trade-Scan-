"""Tests for the cointegration human-view projection (P4).

Pure DataFrame -> DataFrame; no Excel. Guards the column budget, the
deterministic multi-key sort (with recency tiebreak), the friendly rename,
and the derived pair / backtest / run_date columns.
"""
import pandas as pd

from tools.portfolio.cointegration_view import (
    COINTEGRATION_VIEW_BUDGET,
    COINTEGRATION_VIEW_COLUMNS,
    build_cointegration_view_df,
)


def _raw(rows):
    return pd.DataFrame(rows)


def _row(run_id, ret_dd, completed, pair_a="EURUSD", pair_b="GER40",
         methodology_version="v1_raw_adf"):
    return {
        "run_id": run_id,
        "pair_a": pair_a, "pair_b": pair_b,
        "timeframe": "1d", "lookback_days": 252,
        "completed_at_utc": completed,
        "test_start": "2025-01-01", "test_end": "2025-06-01",
        "canonical_ret_dd": ret_dd, "canonical_net_pct": 12.5,
        "canonical_max_dd_pct": 8.0, "canonical_final_equity_usd": 1125.0,
        "trades_total": 42, "cycles_completed": 11, "cycle_win_rate_pct": 55.0,
        "regime_state": "cointegrated",
        "backtests_path": f"backtests/{run_id}_X",
        "methodology_version": methodology_version,
    }


def test_empty_returns_view_columns():
    out = build_cointegration_view_df(pd.DataFrame())
    assert list(out.columns) == COINTEGRATION_VIEW_COLUMNS
    assert len(out) == 0


def test_column_budget_not_exceeded():
    out = build_cointegration_view_df(_raw([_row("R1", 1.5, "2026-05-28T00:00:00Z")]))
    assert len(out.columns) <= COINTEGRATION_VIEW_BUDGET
    assert list(out.columns) == COINTEGRATION_VIEW_COLUMNS


def test_friendly_rename_and_no_canonical_names():
    out = build_cointegration_view_df(_raw([_row("R1", 1.5, "2026-05-28T00:00:00Z")]))
    assert "return_dd_ratio" in out.columns
    assert "max drawdown %" in out.columns
    assert "total_trades" in out.columns and "win_rate" in out.columns
    assert "canonical_ret_dd" not in out.columns
    assert "trades_total" not in out.columns
    # methodology column carries the cohort tag (C4 2026-05-30).
    assert "methodology" in out.columns
    assert "methodology_version" not in out.columns  # renamed away
    assert out.iloc[0]["methodology"] == "v1_raw_adf"


def test_methodology_passes_through_per_row():
    """Mixed-cohort corpus: v1 legacy rows and v2 post-correction rows must
    display side by side with their own methodology tag (the operator's
    primary signal that the two methodologies are not comparable)."""
    out = build_cointegration_view_df(_raw([
        _row("V1ROW", 1.5, "2026-05-15T00:00:00Z", methodology_version="v1_raw_adf"),
        _row("V2ROW", 2.0, "2026-05-30T00:00:00Z", methodology_version="v2_log_eg"),
    ]))
    by_run_date = dict(zip(out["run_date"], out["methodology"]))
    assert by_run_date["2026-05-15"] == "v1_raw_adf"
    assert by_run_date["2026-05-30"] == "v2_log_eg"


def test_sort_primary_by_ret_dd_desc():
    out = build_cointegration_view_df(_raw([
        _row("LOW", 0.5, "2026-05-01T00:00:00Z"),
        _row("HIGH", 3.0, "2026-05-01T00:00:00Z"),
        _row("MID", 1.5, "2026-05-01T00:00:00Z"),
    ]))
    assert out["return_dd_ratio"].tolist() == [3.0, 1.5, 0.5]
    assert out["rank"].tolist() == [1, 2, 3]


def test_exact_tie_breaks_by_recency():
    # identical ret_dd -> the more recent completed_at_utc must rank higher
    out = build_cointegration_view_df(_raw([
        _row("OLD", 2.0, "2026-05-01T00:00:00Z"),
        _row("NEW", 2.0, "2026-05-20T00:00:00Z"),
    ]))
    assert out.iloc[0]["backtest"] == "NEW_X"   # newest floats up
    assert out.iloc[1]["backtest"] == "OLD_X"


def test_derived_pair_backtest_rundate():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.5, "2026-05-28T09:30:00Z", pair_a="GER40", pair_b="EURUSD"),
    ]))
    assert out.iloc[0]["pair"] == "GER40 / EURUSD"
    assert out.iloc[0]["backtest"] == "R1_X"
    assert out.iloc[0]["run_date"] == "2026-05-28"
