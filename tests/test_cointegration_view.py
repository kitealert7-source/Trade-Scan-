"""Tests for the cointegration human-view projection (P4).

Pure DataFrame -> DataFrame; no Excel. Guards the column budget, the
deterministic multi-key sort (with recency tiebreak), the friendly rename,
and the derived pair / backtest / run_date / pair_class / coint_friendly /
all_profitable columns.
"""
import pandas as pd
import pytest

from tools.portfolio.cointegration_view import (
    COINTEGRATION_VIEW_BUDGET,
    COINTEGRATION_VIEW_COLUMNS,
    build_cointegration_view_df,
)


def _raw(rows):
    return pd.DataFrame(rows)


def _row(run_id, ret_dd, completed, pair_a="EURUSD", pair_b="GER40",
         methodology_version="v1_raw_adf",
         directive_id=None, continuous_span_obs=50, net_pct=12.5,
         test_start="2025-01-01", test_end="2025-06-01"):
    return {
        "run_id": run_id,
        "directive_id": directive_id if directive_id is not None else f"DIR_{run_id}",
        "pair_a": pair_a, "pair_b": pair_b,
        "timeframe": "1d", "lookback_days": 252,
        "completed_at_utc": completed,
        "test_start": test_start, "test_end": test_end,
        "canonical_ret_dd": ret_dd, "canonical_net_pct": net_pct,
        "canonical_max_dd_pct": 8.0, "canonical_final_equity_usd": 1125.0,
        "trades_total": 42, "cycles_completed": 11, "cycle_win_rate_pct": 55.0,
        "regime_state": "cointegrated",
        "continuous_span_obs": continuous_span_obs,
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


def test_column_budget_locked_at_20():
    # The cap is asserted explicitly so an accidental addition to
    # COINTEGRATION_VIEW_COLUMNS without a budget bump fails loudly.
    assert COINTEGRATION_VIEW_BUDGET == 20
    assert len(COINTEGRATION_VIEW_COLUMNS) == 20


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


# ---------- pair_class taxonomy ----------

def test_pair_class_FX():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="EURUSD", pair_b="GBPUSD"),
        _row("R2", 1.0, "2026-05-28T00:00:00Z", pair_a="AUDJPY", pair_b="CADJPY"),
    ]))
    assert set(out["pair_class"]) == {"FX"}


def test_pair_class_IDX():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="GER40", pair_b="UK100"),
    ]))
    assert out.iloc[0]["pair_class"] == "IDX"


def test_pair_class_Cross_FX_IDX():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="CHFJPY", pair_b="UK100"),
        _row("R2", 1.0, "2026-05-28T00:00:00Z", pair_a="GER40", pair_b="EURUSD"),
    ]))
    assert set(out["pair_class"]) == {"Cross"}


def test_pair_class_Crypto():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="BTCUSD", pair_b="ETHUSD"),
    ]))
    assert out.iloc[0]["pair_class"] == "Crypto"


def test_pair_class_Crypto_overrides_FX():
    # BTCUSD+EURUSD must land in Crypto, NOT Cross.
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="BTCUSD", pair_b="EURUSD"),
    ]))
    assert out.iloc[0]["pair_class"] == "Crypto"


def test_pair_class_Metals_overrides_FX():
    # XAUUSD+EURUSD must land in Metals, NOT Cross or FX.
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="XAUUSD", pair_b="EURUSD"),
    ]))
    assert out.iloc[0]["pair_class"] == "Metals"


def test_pair_class_raises_on_unenumerated_symbol():
    # The column's value set is closed (no Unknown bucket). An unenumerated
    # symbol must fail loudly so the taxonomy is updated rather than silently
    # miscategorized into Cross.
    with pytest.raises(ValueError, match="unenumerated symbol"):
        build_cointegration_view_df(_raw([
            _row("R1", 1.0, "2026-05-28T00:00:00Z", pair_a="TSLA", pair_b="EURUSD"),
        ]))


def test_pair_class_new_cols_positioned_after_lookback():
    # Operator preference: filter aids sit between `lookback` (col D) and
    # `run_date`, NOT at the right edge — they're filtered before the user
    # scrolls right to see metrics.
    cols = COINTEGRATION_VIEW_COLUMNS
    assert cols.index("pair_class") == cols.index("lookback") + 1
    assert cols.index("coint_friendly") == cols.index("pair_class") + 1
    assert cols.index("all_profitable") == cols.index("coint_friendly") + 1
    assert cols.index("run_date") == cols.index("all_profitable") + 1


# ---------- coint_friendly thresholds ----------

def test_coint_friendly_STRONG_at_90():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", continuous_span_obs=90),
    ]))
    assert out.iloc[0]["coint_friendly"] == "STRONG"


def test_coint_friendly_FRIENDLY_at_89():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", continuous_span_obs=89),
    ]))
    assert out.iloc[0]["coint_friendly"] == "FRIENDLY"


def test_coint_friendly_FRIENDLY_at_30():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", continuous_span_obs=30),
    ]))
    assert out.iloc[0]["coint_friendly"] == "FRIENDLY"


def test_coint_friendly_WEAK_at_29():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", continuous_span_obs=29),
    ]))
    assert out.iloc[0]["coint_friendly"] == "WEAK"


def test_coint_friendly_WEAK_at_NaN():
    out = build_cointegration_view_df(_raw([
        _row("R1", 1.0, "2026-05-28T00:00:00Z", continuous_span_obs=None),
    ]))
    assert out.iloc[0]["coint_friendly"] == "WEAK"


# ---------- all_profitable cross-run pair flag ----------

def _runs(pair_a, pair_b, nets, test_start="2025-01-01", test_end="2025-03-01"):
    """Helper: emit one run (row) per net% in `nets`, all for the same pair.
    The flag is pair-level (across every run and window), so the window only
    matters when a test deliberately spreads runs across multiple windows."""
    return [
        _row(f"{pair_a}{pair_b}_{i}", 1.0, "2026-05-28T00:00:00Z",
             pair_a=pair_a, pair_b=pair_b,
             directive_id=f"90_PORT_{pair_a}{pair_b}_15M_X_{i}",
             net_pct=net, test_start=test_start, test_end=test_end)
        for i, net in enumerate(nets)
    ]


def test_all_profitable_Yes_when_every_run_positive():
    out = build_cointegration_view_df(_raw(
        _runs("EURUSD", "GBPUSD", [5.0, 3.0, 0.1, 12.0])
    ))
    assert set(out["all_profitable"].tolist()) == {"Yes"}


def test_all_profitable_No_when_any_run_negative():
    # One losing run among many winners drops the whole pair to No.
    out = build_cointegration_view_df(_raw(
        _runs("EURUSD", "GBPUSD", [5.0, 3.0, -0.4, 12.0])
    ))
    assert set(out["all_profitable"].tolist()) == {"No"}


def test_all_profitable_No_when_any_run_break_even():
    # Break-even (0.0) is not > 0, so it counts against the pair.
    out = build_cointegration_view_df(_raw(
        _runs("EURUSD", "GBPUSD", [5.0, 0.0, 3.0])
    ))
    assert set(out["all_profitable"].tolist()) == {"No"}


def test_all_profitable_single_run_pair_gets_verdict_not_blank():
    # The retired both_profitable left single-variant pairs blank; every pair
    # now gets a Yes/No verdict.
    yes = build_cointegration_view_df(_raw(_runs("EURUSD", "GBPUSD", [2.0])))
    no = build_cointegration_view_df(_raw(_runs("AUDUSD", "NZDUSD", [-2.0])))
    assert yes.iloc[0]["all_profitable"] == "Yes"
    assert no.iloc[0]["all_profitable"] == "No"


def test_all_profitable_spans_all_windows():
    # One pair, two windows: window A all-positive, window B has a loser. The
    # screen is across ALL windows, so every row of the pair is labelled No.
    rows = (
        _runs("EURUSD", "GBPUSD", [5.0, 3.0],
              test_start="2025-01-01", test_end="2025-03-01") +
        _runs("EURUSD", "GBPUSD", [4.0, -1.0],
              test_start="2025-04-01", test_end="2025-06-01")
    )
    out = build_cointegration_view_df(_raw(rows))
    assert set(out["all_profitable"].tolist()) == {"No"}


def test_all_profitable_independent_per_pair():
    # Two distinct pairs get independent verdicts; the merge must not collapse
    # one pair's outcome onto the other.
    rows = (
        _runs("EURUSD", "GBPUSD", [5.0, 3.0]) +
        _runs("AUDUSD", "NZDUSD", [5.0, -1.0])
    )
    out = build_cointegration_view_df(_raw(rows))
    by_pair = out.groupby("pair")["all_profitable"].agg(set).to_dict()
    assert by_pair["EURUSD / GBPUSD"] == {"Yes"}
    assert by_pair["AUDUSD / NZDUSD"] == {"No"}
