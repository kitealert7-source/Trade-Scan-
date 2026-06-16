"""Deployability provenance (2026-06-16): the `comparison` ledger is EVIDENCE --
a row exists IFF two certified runs were a valid, apples-to-apples basis for a
decision. There is no status column; existence is the certification.

    comparison row exists  ->  deployment evidence exists
    comparison row absent  ->  deployment evidence does not exist

These tests lock the refusal discipline: invalid evidence is NOT representable.
"""
import sqlite3

import pytest

from tools.ledger_db import create_tables, upsert_cointegration_row
from tools.portfolio.comparison_schema import COMPARISON_COLUMNS
from tools.portfolio.comparison_writer import certify_comparison, ComparisonError

_D = "d" * 64  # an effective_input_sha256 value


def _conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    create_tables(conn)
    return conn


def _seed(conn, run_id, *, eff=_D, engine_v="1.5.9", engine_abi="engine_abi.v1_5_9",
          dsha, is_current=1):
    """Seed a cointegration_sheet run. Default = certified (current + witness-complete)."""
    upsert_cointegration_row(conn, {
        "run_id": run_id,
        "effective_input_sha256": eff,
        "engine_version": engine_v,
        "engine_abi": engine_abi,
        "directive_sha256": dsha,
        "is_current": is_current,
    })


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM comparison").fetchone()[0]


def test_existence_is_the_certification_no_status_column():
    """The design: a row's existence certifies it; there is no comparable/status col."""
    assert "comparison_id" in COMPARISON_COLUMNS
    for forbidden in ("comparable", "data_match", "engine_match", "directive_differs"):
        assert forbidden not in COMPARISON_COLUMNS


def test_valid_comparison_is_recorded_as_evidence(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn, "BBK25", dsha="dir_bbk25")
    _seed(conn, "FXD25", dsha="dir_fxd25")
    row = certify_comparison(conn, "BBK25", "FXD25", "deployability: BBK25 vs FXD25")
    assert row["left_run_id"] == "BBK25" and row["right_run_id"] == "FXD25"
    # existence == certification: the deployment-evidence lookup finds it
    assert conn.execute(
        "SELECT 1 FROM comparison WHERE left_run_id='BBK25' AND right_run_id='FXD25'"
    ).fetchone() is not None
    conn.close()


def test_refuses_different_data_and_writes_nothing(tmp_path):
    """Data-drift (BB turnover #1): not apples-to-apples -> refused, no row."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=_D, dsha="dir_L")
    _seed(conn, "R", eff="e" * 64, dsha="dir_R")
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "L", "R", "x")
    assert _count(conn) == 0
    conn.close()


def test_refuses_different_engine(tmp_path):
    """Engine-confound (BB turnover #2): refused."""
    conn = _conn(tmp_path)
    _seed(conn, "L", engine_v="1.5.9", dsha="dir_L")
    _seed(conn, "R", engine_v="1.5.10", dsha="dir_R")
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "L", "R", "x")
    assert _count(conn) == 0
    conn.close()


def test_refuses_identical_directive(tmp_path):
    """No intended delta (same directive / self-comparison): not a comparison."""
    conn = _conn(tmp_path)
    _seed(conn, "L", dsha="same")
    _seed(conn, "R", dsha="same")
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "L", "R", "x")
    assert _count(conn) == 0
    conn.close()


def test_refuses_non_current_run(tmp_path):
    """The 'right run' rule: a superseded (is_current=0) run is NOT certified."""
    conn = _conn(tmp_path)
    _seed(conn, "CUR", dsha="dir_cur", is_current=1)
    _seed(conn, "OLD", dsha="dir_old", is_current=0)
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "CUR", "OLD", "x")
    assert _count(conn) == 0
    conn.close()


def test_refuses_witness_incomplete_run(tmp_path):
    """A run with a NULL identity witness cannot be evidence (e.g. pre-2026-06-16)."""
    conn = _conn(tmp_path)
    _seed(conn, "OK", dsha="dir_ok")
    _seed(conn, "NOWIT", eff=None, dsha="dir_nowit")  # NULL effective_input_sha256
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "OK", "NOWIT", "x")
    assert _count(conn) == 0
    conn.close()


def test_refuses_unknown_run(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn, "L", dsha="dir_L")
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "L", "GHOST", "x")
    assert _count(conn) == 0
    conn.close()


def test_idempotent_single_row(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn, "L", dsha="dir_L")
    _seed(conn, "R", dsha="dir_R")
    certify_comparison(conn, "L", "R", "same reason")
    certify_comparison(conn, "L", "R", "same reason")
    assert _count(conn) == 1
    conn.close()
