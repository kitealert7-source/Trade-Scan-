"""Tests for the cointegration human-view projection (P4).

Pure DataFrame -> DataFrame; no Excel. Guards the column budget, the
deterministic multi-key sort (with recency tiebreak), the friendly rename,
and the derived pair / backtest / run_date / pair_class / coint_friendly /
both_profitable columns.
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
    assert cols.index("both_profitable") == cols.index("coint_friendly") + 1
    assert cols.index("run_date") == cols.index("both_profitable") + 1


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


# ---------- both_profitable paired-group join ----------

def _paired(pair_a, pair_b, episode_start, episode_end, baseline_net, zcross_net):
    """Helper: emit baseline + zcross rows for a single (pair, episode) group."""
    base_id = f"90_PORT_{pair_a}{pair_b}_15M_X__E{episode_start.replace('-','')}"
    zcross_id = f"90_PORT_{pair_a}{pair_b}_15M_X_ZCRS_E{episode_start.replace('-','')}"
    return [
        _row(f"B_{episode_start}", 1.0, "2026-05-28T00:00:00Z",
             pair_a=pair_a, pair_b=pair_b,
             directive_id=base_id, net_pct=baseline_net,
             test_start=episode_start, test_end=episode_end),
        _row(f"Z_{episode_start}", 1.0, "2026-05-28T00:00:00Z",
             pair_a=pair_a, pair_b=pair_b,
             directive_id=zcross_id, net_pct=zcross_net,
             test_start=episode_start, test_end=episode_end),
    ]


def test_both_profitable_Yes_when_both_variants_positive():
    out = build_cointegration_view_df(_raw(
        _paired("EURUSD", "GBPUSD", "2025-01-01", "2025-03-01",
                baseline_net=5.0, zcross_net=3.0)
    ))
    assert set(out["both_profitable"].dropna().tolist()) == {"Yes"}
    assert len(out) == 2


def test_both_profitable_No_when_baseline_negative():
    out = build_cointegration_view_df(_raw(
        _paired("EURUSD", "GBPUSD", "2025-01-01", "2025-03-01",
                baseline_net=-2.0, zcross_net=4.0)
    ))
    assert set(out["both_profitable"].dropna().tolist()) == {"No"}


def test_both_profitable_No_when_zcross_negative():
    out = build_cointegration_view_df(_raw(
        _paired("EURUSD", "GBPUSD", "2025-01-01", "2025-03-01",
                baseline_net=5.0, zcross_net=-1.0)
    ))
    assert set(out["both_profitable"].dropna().tolist()) == {"No"}


def test_both_profitable_blank_on_baseline_only_orphan():
    # Mirrors the 10 baseline-only orphans in the v2_log_eg corpus.
    out = build_cointegration_view_df(_raw([
        _row("ORPHAN", 1.0, "2026-05-28T00:00:00Z",
             pair_a="EURUSD", pair_b="GBPUSD",
             directive_id="90_PORT_EURUSDGBPUSD_15M_X__E250101",
             net_pct=4.0,
             test_start="2025-01-01", test_end="2025-03-01"),
    ]))
    # Orphan -> NA (blank in Excel; naturally drops out of `== True` filter).
    assert pd.isna(out.iloc[0]["both_profitable"])


def test_both_profitable_independent_per_episode():
    # Two episodes for the same pair: episode A both profitable, episode B
    # only baseline profitable. The merge must label each row by its own
    # group's outcome, not collapse across episodes.
    rows = (
        _paired("EURUSD", "GBPUSD", "2025-01-01", "2025-03-01",
                baseline_net=5.0, zcross_net=3.0) +
        _paired("EURUSD", "GBPUSD", "2025-04-01", "2025-06-01",
                baseline_net=5.0, zcross_net=-1.0)
    )
    out = build_cointegration_view_df(_raw(rows))
    by_episode = out.groupby("test_start")["both_profitable"].agg(set).to_dict()
    assert by_episode["2025-01-01"] == {"Yes"}
    assert by_episode["2025-04-01"] == {"No"}
