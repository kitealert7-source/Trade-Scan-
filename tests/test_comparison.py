"""Deployability provenance (2026-06-16): the `comparison` ledger certifies that
two SPECIFIC runs were apples-to-apples, so "can I trust left > right enough to
deploy?" is a single ledger lookup, not forensics.

These tests lock the success criterion AND the tri-state honesty: a missing
witness must read `indeterminate`, never `yes` -- the exact failure mode (a green
signal that guarantees the wrong thing) this whole audit exists to prevent.
"""
import sqlite3

import pytest

from tools.ledger_db import create_tables, upsert_cointegration_row
from tools.portfolio.comparison_writer import certify_comparison, ComparisonError

_D = "d" * 64  # an effective_input_sha256 value


def _conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    create_tables(conn)
    return conn


def _seed(conn, run_id, *, eff, engine_v="1.5.9", engine_abi="engine_abi.v1_5_9", dsha):
    """Insert a minimal cointegration_sheet row carrying the three witnesses."""
    upsert_cointegration_row(conn, {
        "run_id": run_id,
        "effective_input_sha256": eff,
        "engine_version": engine_v,
        "engine_abi": engine_abi,
        "directive_sha256": dsha,
    })


def test_same_data_same_engine_diff_directive_is_comparable(tmp_path):
    """The success criterion: identical effective data + engine, intended directive
    delta -> comparable=yes, answerable in one query."""
    conn = _conn(tmp_path)
    _seed(conn, "BBK25", eff=_D, dsha="dir_bbk25")
    _seed(conn, "FXD25", eff=_D, dsha="dir_fxd25")
    cert = certify_comparison(conn, "BBK25", "FXD25", "deployability: BBK25 vs FXD25")
    assert cert["data_match"] == "yes"
    assert cert["engine_match"] == "yes"
    assert cert["directive_differs"] == "yes"
    assert cert["comparable"] == "yes"
    # the deployability lookup
    got = conn.execute(
        "SELECT comparable FROM comparison WHERE left_run_id='BBK25' AND right_run_id='FXD25'"
    ).fetchone()
    assert got[0] == "yes"
    conn.close()


def test_different_data_is_not_comparable(tmp_path):
    """Data-drift (turnover #1 of BB-adaptive): caught as comparable=no."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=_D, dsha="dir_L")
    _seed(conn, "R", eff="e" * 64, dsha="dir_R")  # different effective data
    cert = certify_comparison(conn, "L", "R", "x")
    assert cert["data_match"] == "no"
    assert cert["comparable"] == "no"
    conn.close()


def test_different_engine_is_not_comparable(tmp_path):
    """Engine-confound: different engine stamp -> comparable=no."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=_D, engine_v="1.5.9", dsha="dir_L")
    _seed(conn, "R", eff=_D, engine_v="1.5.10", dsha="dir_R")
    cert = certify_comparison(conn, "L", "R", "x")
    assert cert["engine_match"] == "no"
    assert cert["comparable"] == "no"
    conn.close()


def test_missing_data_witness_is_indeterminate_not_yes(tmp_path):
    """The anti-pattern guard: a NULL witness must NEVER read as comparable."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=None, dsha="dir_L")   # pre-witness run (e.g. < 2026-06-16)
    _seed(conn, "R", eff=_D, dsha="dir_R")
    cert = certify_comparison(conn, "L", "R", "x")
    assert cert["data_match"] == "indeterminate"
    assert cert["comparable"] == "indeterminate"   # NOT "yes"
    conn.close()


def test_same_directive_is_not_a_valid_comparison(tmp_path):
    """No intended delta (same directive / self-comparison) -> comparable=no."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=_D, dsha="same_dir")
    _seed(conn, "R", eff=_D, dsha="same_dir")
    cert = certify_comparison(conn, "L", "R", "x")
    assert cert["directive_differs"] == "no"
    assert cert["comparable"] == "no"
    conn.close()


def test_unknown_run_id_fatals(tmp_path):
    """A comparison referencing a run absent from the ledger is rejected loudly."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=_D, dsha="dir_L")
    with pytest.raises(ComparisonError):
        certify_comparison(conn, "L", "GHOST", "x")
    conn.close()


def test_append_only_idempotent(tmp_path):
    """Identical (left, right, reason) is one immutable row, not a duplicate."""
    conn = _conn(tmp_path)
    _seed(conn, "L", eff=_D, dsha="dir_L")
    _seed(conn, "R", eff=_D, dsha="dir_R")
    certify_comparison(conn, "L", "R", "same reason")
    certify_comparison(conn, "L", "R", "same reason")
    n = conn.execute(
        "SELECT COUNT(*) FROM comparison WHERE left_run_id='L' AND right_run_id='R'"
    ).fetchone()[0]
    assert n == 1
    conn.close()
