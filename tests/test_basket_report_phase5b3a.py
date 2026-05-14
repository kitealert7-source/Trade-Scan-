"""Phase 5b.3a tests — per-window basket report emitter.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.3a (option 3 of the
artifact-discoverability gap report).

Covers:
  - compute_basket_metrics returns the four metric blocks (standard,
    risk, yearwise, basket telemetry, per-leg)
  - write_per_window_report_artifacts produces all 8 expected files
    (standard, risk, yearwise, basket, glossary, bar_geometry,
     metadata, REPORT.md)
  - Schema fidelity: results_standard.csv columns match per-symbol
    convention; results_risk.csv same
  - REPORT.md contains the directive_id, basket_id, rule reference,
    leg composition table, top-line metrics
  - bar_geometry.json picks the right median_bar_seconds per timeframe
  - Empty-trades case doesn't crash
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---- helpers ---------------------------------------------------------------


def _basket_result(per_leg_trades=None, recycle_events=None,
                   harvested_total_usd=0.0, exit_reason=None):
    from tools.basket_pipeline import BasketRunResult
    r = BasketRunResult(
        basket_id="H2",
        legs=[
            {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
            {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
        ],
        per_leg_trades=per_leg_trades or {"EURUSD": [], "USDJPY": []},
        recycle_events=recycle_events or [],
        harvested_total_usd=harvested_total_usd,
        rule_name="H2_recycle", rule_version=1,
    )
    if exit_reason is not None:
        r.exit_reason = exit_reason
    return r


def _trades_df(rows):
    """Build a tradelevel DataFrame matching the converter's schema."""
    from tools.basket_ledger import PER_SYMBOL_TRADE_COLUMNS
    df = pd.DataFrame(rows)
    # Pad with missing columns
    for col in PER_SYMBOL_TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[PER_SYMBOL_TRADE_COLUMNS]


def _directive(timeframe="5m"):
    return {
        "test": {"name": "90_PORT_H2_5M_RECYCLE_S01_V1_P00",
                 "strategy": "90_PORT_H2_5M_RECYCLE_S01_V1_P00",
                 "timeframe": timeframe, "broker": "OctaFx",
                 "start_date": "2024-09-02", "end_date": "2024-09-30"},
        "basket": {
            "basket_id": "H2",
            "initial_stake_usd": 1000.0,
            "legs": [
                {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
                {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
            ],
            "recycle_rule": {"name": "H2_recycle", "version": 1, "params": {}},
        },
    }


# ---- compute_basket_metrics -----------------------------------------------


def test_compute_basket_metrics_returns_all_blocks():
    from tools.basket_report import compute_basket_metrics
    df = _trades_df([
        {"symbol": "EURUSD", "pnl_usd": 25.0, "exit_timestamp": "2024-09-10"},
        {"symbol": "EURUSD", "pnl_usd": -8.0, "exit_timestamp": "2024-09-12"},
        {"symbol": "USDJPY", "pnl_usd": 15.0, "exit_timestamp": "2024-09-15"},
    ])
    result = _basket_result(recycle_events=[{"r": 1}], harvested_total_usd=0.0)
    metrics = compute_basket_metrics(df, result, starting_equity=1000.0)
    assert set(metrics.keys()) == {"standard", "risk", "yearwise", "basket", "per_leg"}
    assert metrics["standard"]["net_pnl_usd"] == 32.0
    assert metrics["standard"]["trade_count"] == 3
    assert metrics["standard"]["win_rate"] == round(2/3, 4)
    assert metrics["basket"]["recycle_event_count"] == 1
    assert metrics["basket"]["harvested_total_usd"] == 0.0
    assert metrics["basket"]["final_realized_usd"] == 32.0
    # Per-leg breakdown has both symbols
    assert set(metrics["per_leg"]["symbol"]) == {"EURUSD", "USDJPY"}


def test_compute_basket_metrics_empty_trades():
    from tools.basket_report import compute_basket_metrics
    df = _trades_df([])
    result = _basket_result()
    metrics = compute_basket_metrics(df, result, starting_equity=1000.0)
    assert metrics["standard"]["trade_count"] == 0
    assert metrics["standard"]["net_pnl_usd"] == 0.0
    assert metrics["risk"]["max_drawdown_usd"] == 0.0
    # yearwise + per_leg are empty DataFrames
    assert metrics["yearwise"].empty
    assert metrics["per_leg"].empty


def test_drawdown_computed_correctly():
    """Cumulative PnL = [10, 25, 15, 5, 30] -> peak=25, trough=5, DD=20."""
    from tools.basket_report import compute_basket_metrics
    pnls = [10, 15, -10, -10, 25]
    df = _trades_df([
        {"symbol": "EURUSD", "pnl_usd": p, "exit_timestamp": f"2024-09-{i+1:02d}"}
        for i, p in enumerate(pnls)
    ])
    result = _basket_result()
    metrics = compute_basket_metrics(df, result, starting_equity=1000.0)
    # Cumulative: 10, 25, 15, 5, 30. Peak before each: 10, 25, 25, 25, 30.
    # Drawdown: 0, 0, 10, 20, 0. Max DD = $20.
    assert metrics["risk"]["max_drawdown_usd"] == 20.0
    assert abs(metrics["risk"]["max_drawdown_pct"] - 0.02) < 1e-9


# ---- write_per_window_report_artifacts ------------------------------------


def test_write_per_window_report_artifacts_produces_all_files(tmp_path):
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([
        {"symbol": "EURUSD", "pnl_usd": 25.0, "exit_timestamp": "2024-09-10"},
        {"symbol": "USDJPY", "pnl_usd": 15.0, "exit_timestamp": "2024-09-15"},
    ])
    result = _basket_result(
        per_leg_trades={"EURUSD": [{"pnl_usd": 25.0}], "USDJPY": [{"pnl_usd": 15.0}]},
        recycle_events=[{"r": 1}],
    )
    written = write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="RID01", directive_id="dir_xyz",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8", starting_equity=1000.0,
    )
    expected_purposes = {"standard", "risk", "yearwise", "basket",
                         "glossary", "bar_geometry", "metadata", "report"}
    assert set(written.keys()) == expected_purposes
    for purpose, path in written.items():
        assert path.is_file(), f"missing: {purpose} -> {path}"
        assert path.stat().st_size > 0, f"empty: {purpose}"


def test_results_standard_schema_matches_per_symbol(tmp_path):
    """results_standard.csv MUST have exactly the per-symbol column set so
    downstream tools that load per-symbol results work on basket rows."""
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([{"symbol": "EURUSD", "pnl_usd": 10.0, "exit_timestamp": "2024-09-10"}])
    result = _basket_result(per_leg_trades={"EURUSD": [{"pnl_usd": 10.0}], "USDJPY": []})
    write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="RID01", directive_id="dir",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8",
    )
    df_std = pd.read_csv(tmp_path / "raw" / "results_standard.csv")
    expected = ["net_pnl_usd", "trade_count", "win_rate", "profit_factor",
                "gross_profit", "gross_loss"]
    assert list(df_std.columns) == expected


def test_results_risk_schema_matches_per_symbol(tmp_path):
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([{"symbol": "EURUSD", "pnl_usd": 10.0, "exit_timestamp": "2024-09-10"}])
    result = _basket_result()
    write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="RID01", directive_id="dir",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8",
    )
    df_risk = pd.read_csv(tmp_path / "raw" / "results_risk.csv")
    expected = ["max_drawdown_usd", "max_drawdown_pct", "return_dd_ratio",
                "sharpe_ratio", "sortino_ratio", "k_ratio", "sqn"]
    assert list(df_risk.columns) == expected


def test_results_basket_telemetry_columns(tmp_path):
    """results_basket.csv has the basket-only telemetry — recycle count,
    harvested total, exit reason."""
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([{"symbol": "EURUSD", "pnl_usd": 10.0, "exit_timestamp": "2024-09-10"}])
    result = _basket_result(recycle_events=[{"r": 1}, {"r": 2}, {"r": 3}],
                            harvested_total_usd=2000.0, exit_reason="TARGET")
    write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="RID01", directive_id="dir",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8",
    )
    df_b = pd.read_csv(tmp_path / "raw" / "results_basket.csv")
    assert list(df_b.columns) == ["recycle_event_count", "harvested_total_usd",
                                   "final_realized_usd", "exit_reason"]
    assert int(df_b["recycle_event_count"].iloc[0]) == 3
    assert float(df_b["harvested_total_usd"].iloc[0]) == 2000.0
    assert df_b["exit_reason"].iloc[0] == "TARGET"


def test_run_metadata_basket_flavored(tmp_path):
    """metadata/run_metadata.json has basket-specific fields."""
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([])
    result = _basket_result()
    write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="RID12345", directive_id="dir_xyz",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8",
    )
    meta = json.loads((tmp_path / "metadata" / "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["run_id"] == "RID12345"
    assert meta["execution_mode"] == "basket"
    assert meta["basket_id"] == "H2"
    assert meta["leg_symbols"] == ["EURUSD", "USDJPY"]
    assert meta["engine_version"] == "1.5.8"
    assert meta["schema_version"] == "1.2.0-basket"
    assert "execution_timestamp_utc" in meta


def test_bar_geometry_per_timeframe(tmp_path):
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([])
    result = _basket_result()
    cases = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
    for tf, expected in cases.items():
        out = tmp_path / tf
        write_per_window_report_artifacts(
            out_dir=out, run_id="X", directive_id="d",
            basket_result=result, df_trades=df, parsed_directive=_directive(timeframe=tf),
            engine_version="1.5.8",
        )
        bg = json.loads((out / "raw" / "bar_geometry.json").read_text(encoding="utf-8"))
        assert bg["median_bar_seconds"] == expected, f"timeframe {tf} got {bg}"


def test_report_md_contains_key_fields(tmp_path):
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([
        {"symbol": "EURUSD", "pnl_usd": 25.0, "exit_timestamp": "2024-09-10"},
        {"symbol": "USDJPY", "pnl_usd": 15.0, "exit_timestamp": "2024-09-15"},
    ])
    result = _basket_result(
        per_leg_trades={"EURUSD": [{"pnl_usd": 25.0}], "USDJPY": [{"pnl_usd": 15.0}]},
        recycle_events=[{"r": 1}],
    )
    write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="RIDABC", directive_id="90_PORT_H2_5M_RECYCLE_S01_V1_P00",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8",
    )
    md = (tmp_path / "REPORT_90_PORT_H2_5M_RECYCLE_S01_V1_P00.md").read_text(encoding="utf-8")
    assert "Basket Report" in md
    assert "90_PORT_H2_5M_RECYCLE_S01_V1_P00" in md
    assert "Run ID: `RIDABC`" in md
    assert "Basket ID: `H2`" in md
    assert "H2_recycle@1" in md
    assert "EURUSD" in md and "USDJPY" in md
    # Top-line metric appears
    assert "Trades" in md
    assert "Profit Factor" in md
    # Basket telemetry section
    assert "Basket Telemetry" in md
    assert "Recycle Events" in md


def test_metrics_glossary_includes_basket_extras(tmp_path):
    from tools.basket_report import write_per_window_report_artifacts
    df = _trades_df([])
    result = _basket_result()
    write_per_window_report_artifacts(
        out_dir=tmp_path, run_id="X", directive_id="d",
        basket_result=result, df_trades=df, parsed_directive=_directive(),
        engine_version="1.5.8",
    )
    glossary = pd.read_csv(tmp_path / "raw" / "metrics_glossary.csv")
    assert set(glossary.columns) == {"metric_key", "full_name", "definition", "unit"}
    keys = set(glossary["metric_key"])
    # Per-symbol keys preserved
    for k in ("net_pnl_usd", "max_drawdown_usd", "sharpe_ratio", "sqn"):
        assert k in keys
    # Basket-only extras present
    for k in ("recycle_event_count", "harvested_total_usd",
              "final_realized_usd", "exit_reason"):
        assert k in keys
