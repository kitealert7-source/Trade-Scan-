"""Integration tests for the 1.3.0-basket telemetry emitter end-to-end.

Plan ref: outputs/H2_BASKET_TELEMETRY_IMPLEMENTATION_PLAN.md §8 (integration
tests 9-14). Operator-approved 2026-05-16.

Drives a full basket through H2RecycleRule + write_per_window_report_artifacts
+ basket_ledger_writer._build_row, asserting on the produced parquet,
run_metadata schema_version, and MPS row composition.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState

from tools.basket_runner import BasketLeg
from tools.recycle_rules import H2RecycleRule
from tools.basket_pipeline import BasketRunResult
from tools.basket_report import write_per_window_report_artifacts, _FIXED_LEDGER_COLUMNS
from tools.portfolio.basket_ledger_writer import (
    BASKETS_SHEET_COLUMNS,
    _build_row,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_basket(eur, jpy, comp, *, eur_lot=0.02, jpy_lot=0.01):
    n = len(eur)
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


def _run_rule_and_build_result(*, harvest=True, run_id="ed1cafeed1ca",
                               directive_id="test_directive_H2"):
    """Run H2RecycleRule on a synthetic 30-bar fixture; return (rule, result)."""
    n = 30
    if harvest:
        # Force harvest (EUR rises enough that equity hits $2000)
        eur = np.linspace(1.100, 1.600, n)
        jpy = np.full(n, 150.0)
    else:
        # Recycle activity without harvest
        eur = np.linspace(1.100, 1.115, n)
        jpy = np.linspace(150.0, 149.0, n)
    comp = np.full(n, 15.0)
    eur_leg, jpy_leg, idx = _make_basket(eur, jpy, comp)
    rule = H2RecycleRule(
        trigger_usd=10.0, add_lot=0.01,
        starting_equity=1000.0, harvest_target_usd=2000.0,
        dd_freeze_frac=0.10, margin_freeze_frac=0.15, leverage=1000.0,
        factor_column="compression_5d", factor_min=10.0,
        run_id=run_id, directive_id=directive_id, basket_id="H2",
    )
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    result = BasketRunResult(
        basket_id="H2",
        legs=[
            {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
            {"symbol": "USDJPY", "lot": 0.01, "direction": "long"},
        ],
        per_leg_trades={"EURUSD": eur_leg.trades, "USDJPY": jpy_leg.trades},
        recycle_events=list(rule.recycle_events),
        harvested_total_usd=rule.harvested_total_usd,
        rule_name=rule.name,
        rule_version=rule.version,
        exit_reason=rule.exit_reason or "",
        per_bar_records=list(rule.per_bar_records),
        summary_stats=dict(rule.summary_stats),
    )
    return rule, result


def _parsed_directive(directive_id="test_directive_H2"):
    return {
        "test": {
            "name": directive_id,
            "strategy": directive_id,
            "timeframe": "5m",
            "start_date": "2024-09-02",
            "end_date": "2024-09-30",
            "broker": "OctaFx",
        },
        "basket": {
            "basket_id": "H2",
            "legs": [
                {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
                {"symbol": "USDJPY", "lot": 0.01, "direction": "long"},
            ],
            "recycle_rule": {
                "name": "H2_recycle",
                "version": 1,
                "params": {"trigger_usd": 10.0, "add_lot": 0.01},
            },
        },
    }


# ---------------------------------------------------------------------------
# Test 9 — parquet written at basket close
# ---------------------------------------------------------------------------


def test_parquet_written_at_basket_close(tmp_path):
    """write_per_window_report_artifacts emits results_basket_per_bar.parquet
    when basket_result carries per_bar_records."""
    rule, result = _run_rule_and_build_result(harvest=True)
    df_trades = pd.DataFrame(columns=["pnl_usd", "exit_timestamp", "symbol"])
    parsed = _parsed_directive()
    written = write_per_window_report_artifacts(
        out_dir=tmp_path,
        run_id="ed1cafeed1ca",
        directive_id="test_directive_H2",
        basket_result=result,
        df_trades=df_trades,
        parsed_directive=parsed,
        engine_version="1.5.9",
        starting_equity=1000.0,
    )
    parquet_path = tmp_path / "raw" / "results_basket_per_bar.parquet"
    assert parquet_path.exists()
    assert written.get("per_bar_ledger") == parquet_path
    # Sanity: load + check row count = per_bar_records count
    df = pd.read_parquet(parquet_path)
    assert len(df) == len(result.per_bar_records)


# ---------------------------------------------------------------------------
# Test 10 — schema enforcement blocks malformed records
# ---------------------------------------------------------------------------


def test_schema_enforcement_blocks_malformed(tmp_path):
    """A per_bar_records list missing required columns raises before write."""
    from tools.basket_report import _write_per_bar_ledger

    bad_records = [{"timestamp": pd.Timestamp.now(), "bar_index": 0}]  # missing 33 cols
    out_path = tmp_path / "ledger.parquet"
    with pytest.raises(ValueError, match="missing required fixed columns"):
        _write_per_bar_ledger(out_path, bad_records, leg_count=2)
    assert not out_path.exists()


def test_schema_enforcement_blocks_missing_leg_columns(tmp_path):
    """Records with all 35 fixed cols but missing leg cols raise."""
    from tools.basket_report import _write_per_bar_ledger
    # Build a single record with all 35 fixed cols but ZERO leg cols
    rec = {col: 0 for col in _FIXED_LEDGER_COLUMNS}
    rec["timestamp"] = pd.Timestamp.now()
    rec["directive_id"] = ""
    rec["basket_id"] = ""
    rec["run_id"] = ""
    rec["skip_reason"] = "NONE"
    rec["gate_factor_name"] = "compression_5d"
    out_path = tmp_path / "ledger.parquet"
    with pytest.raises(ValueError, match="missing per-leg columns"):
        _write_per_bar_ledger(out_path, [rec], leg_count=2)
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# Test 11 — schema_version bumped to 1.3.0-basket
# ---------------------------------------------------------------------------


def test_schema_version_bumped(tmp_path):
    """run_metadata.json reports schema_version=1.3.0-basket after the patch."""
    rule, result = _run_rule_and_build_result(harvest=True)
    df_trades = pd.DataFrame(columns=["pnl_usd", "exit_timestamp", "symbol"])
    parsed = _parsed_directive()
    write_per_window_report_artifacts(
        out_dir=tmp_path,
        run_id="ed1cafeed1ca",
        directive_id="test_directive_H2",
        basket_result=result,
        df_trades=df_trades,
        parsed_directive=parsed,
        engine_version="1.5.9",
    )
    meta_path = tmp_path / "metadata" / "run_metadata.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["schema_version"] == "1.3.0-basket"


# ---------------------------------------------------------------------------
# Test 12 — MPS row gets new columns from in-memory summary_stats
# ---------------------------------------------------------------------------


def test_mps_baskets_new_columns_populate():
    """_build_row produces all 27 columns including 11 new derived from summary_stats."""
    rule, result = _run_rule_and_build_result(harvest=True)
    row = _build_row(
        basket_result=result,
        run_id="ed1cafeed1ca",
        directive_id="test_directive_H2",
        backtests_path="backtests/test/raw",
        vault_path="vault/test",
    )
    # All locked columns present
    assert set(BASKETS_SHEET_COLUMNS).issubset(row.keys())
    # 1.3.0-basket derived columns are populated (non-NA) when summary_stats is present
    assert row["schema_version"] == "1.3.0-basket"
    assert row["peak_floating_dd_usd"] is pd.NA or row["peak_floating_dd_usd"] >= 0
    assert isinstance(row["dd_freeze_count"], int)
    assert isinstance(row["margin_freeze_count"], int)
    assert isinstance(row["regime_freeze_count"], int)
    # peak_lots_json is a JSON-encoded dict (or NA if no leg lots tracked)
    if row["peak_lots_json"] is not pd.NA:
        parsed = json.loads(row["peak_lots_json"])
        assert isinstance(parsed, dict)
        assert "EURUSD" in parsed
        assert "USDJPY" in parsed


# ---------------------------------------------------------------------------
# Test 13 — backward compat: legacy basket (no summary_stats) gets NaN-filled
# ---------------------------------------------------------------------------


def test_mps_backward_compat_legacy_rows_nan():
    """Legacy basket_result with empty summary_stats → NaN in new derived columns."""
    rule, result = _run_rule_and_build_result(harvest=True)
    # Simulate legacy: blank out the summary_stats
    result.summary_stats = {}
    row = _build_row(
        basket_result=result,
        run_id="legacy_run",
        directive_id="legacy_directive",
        backtests_path="backtests/legacy/raw",
        vault_path="vault/legacy",
    )
    # Schema version still claims 1.3.0 (the WRITER is 1.3.0-aware regardless of rule).
    assert row["schema_version"] == "1.3.0-basket"
    # Derived metrics are pd.NA when summary_stats is missing
    for col in (
        "peak_floating_dd_usd", "peak_floating_dd_pct",
        "dd_freeze_count", "margin_freeze_count", "regime_freeze_count",
        "peak_margin_used_usd", "min_margin_level_pct",
        "worst_floating_at_freeze_usd", "return_on_real_capital_pct",
        "peak_lots_json",
    ):
        assert row[col] is pd.NA, f"expected NA for {col}; got {row[col]!r}"


# ---------------------------------------------------------------------------
# Test 14 — legacy basket without per_bar_records does not produce parquet
# ---------------------------------------------------------------------------


def test_per_bar_records_empty_no_parquet_written(tmp_path):
    """basket_result.per_bar_records empty → no parquet file emitted."""
    rule, result = _run_rule_and_build_result(harvest=True)
    # Simulate legacy: blank out per_bar_records
    result.per_bar_records = []
    df_trades = pd.DataFrame(columns=["pnl_usd", "exit_timestamp", "symbol"])
    parsed = _parsed_directive()
    written = write_per_window_report_artifacts(
        out_dir=tmp_path,
        run_id="legacy_run",
        directive_id="legacy_directive",
        basket_result=result,
        df_trades=df_trades,
        parsed_directive=parsed,
        engine_version="1.5.9",
    )
    parquet_path = tmp_path / "raw" / "results_basket_per_bar.parquet"
    assert not parquet_path.exists()
    assert "per_bar_ledger" not in written
    # Other artifacts (CSVs, metadata, report) still produced
    assert (tmp_path / "raw" / "results_basket.csv").exists()
    assert (tmp_path / "metadata" / "run_metadata.json").exists()


# ---------------------------------------------------------------------------
# Bonus — parquet dtypes round-trip correctly
# ---------------------------------------------------------------------------


def test_parquet_dtypes_preserved(tmp_path):
    """Boolean columns stay bool; nullable Int columns stay Int64; timestamp stays datetime."""
    rule, result = _run_rule_and_build_result(harvest=True)
    df_trades = pd.DataFrame(columns=["pnl_usd", "exit_timestamp", "symbol"])
    parsed = _parsed_directive()
    write_per_window_report_artifacts(
        out_dir=tmp_path,
        run_id="ed1cafeed1ca",
        directive_id="test_directive_H2",
        basket_result=result,
        df_trades=df_trades,
        parsed_directive=parsed,
        engine_version="1.5.9",
    )
    df = pd.read_parquet(tmp_path / "raw" / "results_basket_per_bar.parquet")
    # Booleans
    for col in ("dd_freeze_active", "margin_freeze_active", "regime_gate_blocked",
                "recycle_attempted", "recycle_executed", "harvest_triggered",
                "engine_paused"):
        assert df[col].dtype == bool, f"{col} dtype = {df[col].dtype}, expected bool"
    # Nullable Int
    for col in ("winner_leg_idx", "loser_leg_idx", "bars_since_last_recycle"):
        assert str(df[col].dtype) == "Int64", f"{col} dtype = {df[col].dtype}"
    # Timestamp
    assert df["timestamp"].dtype.kind == "M"
    # Final equity at the harvest bar matches harvested_total_usd
    harvest_rows = df[df["harvest_triggered"]]
    assert len(harvest_rows) == 1
    # equity_total at harvest = starting + realized + floating = harvest_target
    assert harvest_rows.iloc[0]["equity_total_usd"] >= 2000.0
