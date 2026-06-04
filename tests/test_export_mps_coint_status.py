"""Tests for the COINT TRADE CANDIDATES "Coint Status (252d)" enrichment wiring
in ledger_db._latest_coint_regime_map (the best-effort cross-DB read).

The view-layer projection is covered in test_trade_candidates_view.py and the
SQL query in test_cointegration_db.py; this guards the orchestrator helper that
joins them at MPS-export time -- specifically the operator-approved decision that
a missing/unreadable screener DB leaves the column blank rather than aborting the
whole MPS regeneration (a scoped exception to Fail-Fast for a non-gating
decision-support column).
"""
from datetime import datetime, timezone
from pathlib import Path

import tools.cointegration_db as cdb
from tools.cointegration_db import DB_COLUMNS, TABLE_NAME, connect, create_tables
from tools.ledger_db import _latest_coint_regime_map


def _seed_screener_db(path: Path, *, tf: str = "1d", lookback_days: int = 252):
    c = connect(path)
    create_tables(c)
    inserted_at = datetime.now(timezone.utc).isoformat()
    c.execute(
        f"INSERT INTO {TABLE_NAME} ({', '.join(DB_COLUMNS)}) "
        f"VALUES ({', '.join(['?']*len(DB_COLUMNS))})",
        ("2026-06-04", "EURUSD", "GBPUSD", tf, lookback_days,
         "2025-01-01", "2026-06-04", lookback_days, 0.03, None, 0, -3.0,
         10.0, 1.5, "ols_static", "eg_mackinnon",
         0.5, "cointegrated", "v0", inserted_at, "v2_log_eg"),
    )
    c.commit()
    c.close()


def test_regime_map_blank_when_screener_db_missing(tmp_path, monkeypatch):
    # SQLITE_DB points at a path that does not exist -> best-effort returns {}.
    monkeypatch.setattr(cdb, "SQLITE_DB", tmp_path / "nope" / "cointegration.db")
    assert _latest_coint_regime_map() == {}


def test_regime_map_reads_seeded_screener_db(tmp_path, monkeypatch):
    db = tmp_path / "cointegration.db"
    _seed_screener_db(db)
    monkeypatch.setattr(cdb, "SQLITE_DB", db)
    assert _latest_coint_regime_map() == {("EURUSD", "GBPUSD"): "cointegrated"}


def test_regime_map_best_effort_swallows_corrupt_db(tmp_path, monkeypatch):
    # A file that exists but is not a valid SQLite DB -> {} (never raises, so the
    # MPS export is never aborted by a bad enrichment source).
    bad = tmp_path / "cointegration.db"
    bad.write_text("not a database", encoding="utf-8")
    monkeypatch.setattr(cdb, "SQLITE_DB", bad)
    assert _latest_coint_regime_map() == {}
