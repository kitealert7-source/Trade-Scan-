"""Data-provenance hardening (2026-06-16): the cointegration ledger carries a
single deterministic DATA witness, `effective_input_sha256`, so two rows answer
"did these runs consume the same effective input data?" from the authoritative
ledger alone -- no manifest, no run folder, no forensics.

SCOPE (asserted here as executable doctrine): the witness attests DATA identity
ONLY. It is folded SOLELY from the existing per-leg `leg_data_sha256` values and
does NOT prove rule-code identity (`strategy_code_sha256` is NULL for baskets) or
sizing identity (`broker_spec_sha256`) -- those remain manifest-only by design.
"""
import inspect
import sqlite3

from tools.basket_provenance import effective_input_sha256
from tools.ledger_db import create_tables, upsert_cointegration_row
from tools.portfolio.cointegration_provenance import build_cointegration_row
from tools.portfolio.cointegration_schema import (
    COINTEGRATION_NUMERIC_COLUMNS,
    COINTEGRATION_SHEET_COLUMNS,
)

_A, _B, _C = "a" * 64, "b" * 64, "c" * 64


def test_identical_leg_data_yields_identical_witness():
    """The success criterion at the value level: same per-leg data hashes
    (in any dict order) -> identical scalar."""
    one = effective_input_sha256({"GBPAUD": _A, "USDCHF": _B})
    two = effective_input_sha256({"USDCHF": _B, "GBPAUD": _A})  # reversed order
    assert one == two
    assert isinstance(one, str) and len(one) == 64


def test_any_leg_change_changes_the_witness():
    base = effective_input_sha256({"GBPAUD": _A, "USDCHF": _B})
    changed = effective_input_sha256({"GBPAUD": _A, "USDCHF": _C})  # one leg differs
    assert base != changed


def test_leg_set_change_changes_the_witness():
    """Binding symbol->hash: dropping/adding a leg is detected, not just hash drift."""
    two_leg = effective_input_sha256({"GBPAUD": _A, "USDCHF": _B})
    one_leg = effective_input_sha256({"GBPAUD": _A})
    assert two_leg != one_leg


def test_none_and_empty_are_null_safe():
    """Provenance never aborts a run: missing input -> NULL column, not an error."""
    assert effective_input_sha256(None) is None
    assert effective_input_sha256({}) is None


def test_deterministic_across_calls():
    legs = {"GBPAUD": _A, "USDCHF": _B}
    assert effective_input_sha256(legs) == effective_input_sha256(dict(legs))


def test_column_is_in_authoritative_schema_and_is_text():
    assert "effective_input_sha256" in COINTEGRATION_SHEET_COLUMNS
    # TEXT decision witness -- never a REAL/numeric column.
    assert "effective_input_sha256" not in COINTEGRATION_NUMERIC_COLUMNS


def test_column_materializes_in_the_ddl(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        create_tables(conn)
        cols = {r[1] for r in conn.execute(
            'PRAGMA table_info("cointegration_sheet")').fetchall()}
        assert "effective_input_sha256" in cols
    finally:
        conn.close()


def test_build_row_accepts_and_carries_the_witness():
    """Wiring lock: the assembler exposes the pass-through kwarg, and the column
    is a recognized schema key (so the writer will not reject it)."""
    params = inspect.signature(build_cointegration_row).parameters
    assert "effective_input_sha256" in params
    assert "effective_input_sha256" in COINTEGRATION_SHEET_COLUMNS


def test_two_ledger_rows_answer_same_effective_data(tmp_path):
    """End-to-end success criterion: future Tony asks 'same effective data?' with
    ONE ledger query -- WHERE effective_input_sha256 = ? -- no manifests."""
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        create_tables(conn)
        same = effective_input_sha256({"GBPAUD": _A, "USDCHF": _B})
        other = effective_input_sha256({"GBPAUD": _A, "USDCHF": _C})
        # No directive_id -> skips the supersession UPDATE; pure insert.
        upsert_cointegration_row(conn, {"run_id": "r1", "effective_input_sha256": same})
        upsert_cointegration_row(conn, {"run_id": "r2", "effective_input_sha256": same})
        upsert_cointegration_row(conn, {"run_id": "r3", "effective_input_sha256": other})
        conn.commit()
        matched = {r[0] for r in conn.execute(
            "SELECT run_id FROM cointegration_sheet WHERE effective_input_sha256 = ?",
            (same,)).fetchall()}
        assert matched == {"r1", "r2"}
    finally:
        conn.close()
