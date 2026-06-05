"""Phase 5b.2 (Path B) acceptance tests — discoverable basket artifacts.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.2.

Path B closes the artifact-discoverability gap from Phase 5b: basket runs
now produce the same artifact shape as per-symbol runs:
  * TradeScan_State/runs/<run_id>/data/results_tradelevel.csv
  * TradeScan_State/backtests/<directive_id>_<basket_id>/raw/
                                                  results_tradelevel.csv
  * TradeScan_State/registry/run_registry.json entry (basket-flavored)
  * Master_Portfolio_Sheet.xlsx Baskets sheet row

Tests cover:
  - basket_ledger.basket_result_to_tradelevel_df produces 31-col schema
    (matches per-symbol contract from PER_SYMBOL_TRADE_COLUMNS)
  - leg_specs_string format: "SYMBOL:lot:direction;..." semicolon-delim
  - basket_ledger_writer.append_basket_row_to_mps writes Baskets sheet,
    leaves Portfolios + Single-Asset Composites untouched, enforces
    append-only on duplicate run_id
  - (End-to-end _try_basket_dispatch artifact-path assertions were moved to
    test_basket_dispatch_e2e.py — consolidated to a single dispatch, 2026-06-05)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---- basket_ledger converter ------------------------------------------------


def test_per_symbol_trade_columns_count_matches_locked_schema():
    """31-column per-symbol schema is the contract; if it changes the
    converter must change in lockstep."""
    from tools.basket_ledger import PER_SYMBOL_TRADE_COLUMNS
    assert len(PER_SYMBOL_TRADE_COLUMNS) == 31


def test_basket_result_to_tradelevel_df_shape_and_pnl():
    """Converter projects per-leg trades into per-symbol-shape rows.
    Verifies USD_QUOTE (EURUSD) and USD_BASE (USDJPY) PnL math."""
    from tools.basket_ledger import basket_result_to_tradelevel_df, PER_SYMBOL_TRADE_COLUMNS
    from tools.basket_pipeline import BasketRunResult

    # Synthetic basket result: one EUR trade (+100 pips, $20) + one JPY trade
    result = BasketRunResult(
        basket_id="H2",
        legs=[
            {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
            {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
        ],
        per_leg_trades={
            "EURUSD": [{"entry_index": 0, "exit_index": 5, "direction": 1,
                        "entry_price": 1.10, "exit_price": 1.11, "pnl_usd": None}],
            "USDJPY": [{"entry_index": 0, "exit_index": 5, "direction": -1,
                        "entry_price": 146.0, "exit_price": 145.0, "pnl_usd": None}],
        },
        recycle_events=[],
        harvested_total_usd=0.0,
        rule_name="H2_recycle", rule_version=1,
    )
    leg_data: dict[str, pd.DataFrame] = {
        "EURUSD": pd.DataFrame({"close": [1.10, 1.11]}, index=pd.date_range("2024-01-01", periods=2, freq="D")),
        "USDJPY": pd.DataFrame({"close": [146.0, 145.0]}, index=pd.date_range("2024-01-01", periods=2, freq="D")),
    }
    df = basket_result_to_tradelevel_df(
        result, run_id="ABCDEF123456", directive_id="dir_xyz", leg_data=leg_data,
    )
    assert df.shape == (2, 31)
    assert list(df.columns) == PER_SYMBOL_TRADE_COLUMNS
    # USD_QUOTE: PnL = direction*lot*100k*(exit-entry) = 1*0.02*100000*0.01 = $20
    eur_row = df[df["symbol"] == "EURUSD"].iloc[0]
    assert abs(float(eur_row["pnl_usd"]) - 20.0) < 1e-6
    # USD_BASE: PnL = direction*lot*100k*(exit-entry)/exit = -1*0.01*100000*-1.0/145.0 = +$6.897
    jpy_row = df[df["symbol"] == "USDJPY"].iloc[0]
    assert abs(float(jpy_row["pnl_usd"]) - (0.01 * 100000 * 1.0 / 145.0)) < 1e-6


def test_leg_specs_string_format():
    """Semicolon-delimited triplets, no JSON. Greppable + parseable."""
    from tools.basket_ledger import leg_specs_string
    legs = [
        {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
        {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
    ]
    assert leg_specs_string(legs) == "EURUSD:0.02:long;USDJPY:0.01:short"


def test_basket_result_to_tradelevel_df_empty_trades():
    """Zero trades -> empty DataFrame with the right schema (loader expects
    all 31 columns even on empty)."""
    from tools.basket_ledger import basket_result_to_tradelevel_df, PER_SYMBOL_TRADE_COLUMNS
    from tools.basket_pipeline import BasketRunResult
    result = BasketRunResult(
        basket_id="EMPTY",
        legs=[{"symbol": "EURUSD", "lot": 0.02, "direction": "long"}],
        per_leg_trades={"EURUSD": []},
        recycle_events=[], harvested_total_usd=0.0,
        rule_name="H2_recycle", rule_version=1,
    )
    df = basket_result_to_tradelevel_df(result, run_id="X", directive_id="d", leg_data={})
    assert df.shape == (0, 31)
    assert list(df.columns) == PER_SYMBOL_TRADE_COLUMNS


# ---- basket_ledger_writer (Baskets sheet) ---------------------------------


def _make_basket_result(**overrides) -> Any:
    from tools.basket_pipeline import BasketRunResult
    defaults = dict(
        basket_id="H2",
        legs=[
            {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
            {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
        ],
        per_leg_trades={"EURUSD": [{"pnl_usd": 20.0}], "USDJPY": [{"pnl_usd": 6.9}]},
        recycle_events=[{"r": 1}, {"r": 2}],
        harvested_total_usd=0.0,
        rule_name="H2_recycle", rule_version=1,
    )
    defaults.update(overrides)
    return BasketRunResult(**defaults)


def test_append_basket_row_to_mps_writes_locked_schema(monkeypatch, tmp_path):
    """First write creates the Baskets sheet with the 16-col locked schema."""
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path)
    (tmp_path / "strategies").mkdir()

    from tools.portfolio.basket_ledger_writer import (
        append_basket_row_to_mps, BASKETS_SHEET_COLUMNS,
    )
    result = _make_basket_result()
    path = append_basket_row_to_mps(
        result, run_id="ABC123XYZ789", directive_id="dir",
        backtests_path="backtests/dir_H2/raw", vault_path="DRY_RUN_VAULT/baskets/dir/H2",
    )
    assert path.is_file()
    with pd.ExcelFile(path) as xls:
        assert "Baskets" in xls.sheet_names
        df = pd.read_excel(xls, sheet_name="Baskets")
    assert list(df.columns) == BASKETS_SHEET_COLUMNS
    assert len(df) == 1
    assert df["run_id"].iloc[0] == "ABC123XYZ789"
    assert df["leg_specs"].iloc[0] == "EURUSD:0.02:long;USDJPY:0.01:short"
    assert int(df["recycle_event_count"].iloc[0]) == 2
    assert abs(float(df["final_realized_usd"].iloc[0]) - 26.9) < 1e-6


def test_append_basket_row_append_only_invariant(monkeypatch, tmp_path):
    """Re-writing the same run_id raises BasketLedgerError (Invariant #2)."""
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path)
    (tmp_path / "strategies").mkdir()

    from tools.portfolio.basket_ledger_writer import (
        append_basket_row_to_mps, BasketLedgerError,
    )
    result = _make_basket_result()
    append_basket_row_to_mps(result, run_id="DUP123", directive_id="d",
                             backtests_path="", vault_path="")
    with pytest.raises(BasketLedgerError, match="(?i)append-only invariant"):
        append_basket_row_to_mps(result, run_id="DUP123", directive_id="d",
                                 backtests_path="", vault_path="")


def test_append_basket_row_preserves_other_sheets(monkeypatch, tmp_path):
    """Writing the Baskets sheet must NOT clobber Portfolios rows.

    Phase 5b.3 (2026-05-20): the writer goes through ledger.db now; the
    xlsx is regenerated from DB on every write. Other-sheet preservation
    therefore means "DB rows for portfolio_sheet survive the basket write",
    not "pre-existing xlsx sheets are surgically preserved".
    """
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path)
    (tmp_path / "strategies").mkdir()
    # ledger_db._connect() resolves LEDGER_DB_PATH dynamically from
    # path_authority.TRADE_SCAN_STATE, so the monkeypatch above is enough.

    # Pre-seed the portfolio_sheet table with two Portfolios rows.
    import tools.ledger_db as ldb
    conn = ldb._connect()
    try:
        ldb.create_tables(conn)
        ldb.upsert_mps_df(conn, pd.DataFrame({
            "portfolio_id": ["fake_p1", "fake_p2"],
            "reference_capital_usd": [1.0, 2.0],
        }), sheet="Portfolios")
    finally:
        conn.close()

    from tools.portfolio.basket_ledger_writer import append_basket_row_to_mps
    result = _make_basket_result()
    append_basket_row_to_mps(result, run_id="RID01", directive_id="d",
                             backtests_path="", vault_path="")

    mps = tmp_path / "strategies" / "Master_Portfolio_Sheet.xlsx"
    with pd.ExcelFile(mps) as xls:
        # Portfolios + Single-Asset Composites + Baskets all present.
        assert "Portfolios" in xls.sheet_names
        assert "Baskets" in xls.sheet_names
        df_p = pd.read_excel(xls, sheet_name="Portfolios")
        df_b = pd.read_excel(xls, sheet_name="Baskets")
    # Portfolios rows survived the basket write.
    assert set(df_p["portfolio_id"]) == {"fake_p1", "fake_p2"}
    # Baskets has our row.
    assert df_b.shape[0] == 1
    assert df_b["run_id"].iloc[0] == "RID01"
