"""P0 schema test for the cointegration_sheet ledger table.

Guards the single-source schema contract (tools/portfolio/cointegration_schema.py)
and the v1 exclusions: NO verdict_status / verdict_logic_version / stored rank.
Also asserts non-entanglement: basket_sheet is unaffected.
"""
import sqlite3

from tools.ledger_db import create_tables, BASKET_SHEET_COLUMNS
from tools.portfolio.cointegration_schema import (
    COINTEGRATION_NUMERIC_COLUMNS,
    COINTEGRATION_SHEET_COLUMNS,
    PRIMARY_KEY,
)


def _info(conn, table):
    return conn.execute(f'PRAGMA table_info("{table}")').fetchall()


def _fresh(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    create_tables(conn)
    return conn


def test_columns_match_single_source(tmp_path):
    conn = _fresh(tmp_path)
    try:
        cols = [r[1] for r in _info(conn, "cointegration_sheet")]
    finally:
        conn.close()
    assert set(cols) == set(COINTEGRATION_SHEET_COLUMNS)
    assert len(cols) == len(COINTEGRATION_SHEET_COLUMNS)


def test_run_id_is_primary_key(tmp_path):
    conn = _fresh(tmp_path)
    try:
        info = _info(conn, "cointegration_sheet")
    finally:
        conn.close()
    # PRAGMA table_info row: (cid, name, type, notnull, dflt_value, pk)
    assert [r[1] for r in info if r[5]] == [PRIMARY_KEY]


def test_numeric_columns_are_real(tmp_path):
    conn = _fresh(tmp_path)
    try:
        types = {r[1]: r[2] for r in _info(conn, "cointegration_sheet")}
    finally:
        conn.close()
    for col in COINTEGRATION_NUMERIC_COLUMNS:
        assert types[col] == "REAL", f"{col} -> {types[col]}"


def test_v1_excludes_verdict_and_rank(tmp_path):
    """Operator guardrail: v1 carries no verdict/rank scaffolding."""
    forbidden = {"verdict_status", "verdict_logic_version", "research_rank", "rank"}
    assert forbidden.isdisjoint(set(COINTEGRATION_SHEET_COLUMNS))
    conn = _fresh(tmp_path)
    try:
        cols = {r[1] for r in _info(conn, "cointegration_sheet")}
    finally:
        conn.close()
    assert forbidden.isdisjoint(cols)


def test_basket_sheet_unaffected(tmp_path):
    """Non-entanglement: basket_sheet still creates with its own schema + verdict."""
    conn = _fresh(tmp_path)
    try:
        cols = {r[1] for r in _info(conn, "basket_sheet")}
    finally:
        conn.close()
    assert set(BASKET_SHEET_COLUMNS).issubset(cols)
    assert "verdict_status" in cols
