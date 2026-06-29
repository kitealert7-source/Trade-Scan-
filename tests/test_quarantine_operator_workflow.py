"""End-to-end acceptance: the operator quarantine workflow releases identity.

Exercises the ACTUAL operator command — rerun_backtest.cmd_finalize(--quarantine) —
against an isolated ledger.db + run_registry.json, and verifies the full contract
that the two-gate consumer change relies on:

  1. ledger row is quarantined (is_current=0, quarantined=1),
  2. run_registry status is "quarantined",
  3. first-exec ownership is released,
  4. sweep ownership is released,
  5. the historical run remains intact (run_id, created_at, and the row all survive).

Pre-assertions prove the gates were LOCKED before the workflow ran, so the test
demonstrates the workflow itself flips them — not a pre-arranged state.

Isolation (see feedback_db_touching_tool_test_isolation): the ledger path resolver,
the global registry path/lock/runs dir, and the two audit sinks are all redirected
to a tmp dir so nothing touches real operational state.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.ledger_db as ledger_db          # noqa: E402
import tools.system_registry as SR           # noqa: E402
import tools.sweep_registry_gate as GATE     # noqa: E402
import tools.rerun_backtest as RB            # noqa: E402

DIRECTIVE = "11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S04_V1_P00"
OLD = "old_polluted_run_aaaa1111"   # the valid-but-contaminated run being quarantined
NEW = "new_superseding_run_bbbb2222"
SYMBOL = "XAUUSD"
CREATED_AT = "2026-06-24T16:59:20+00:00"


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect ledger + global registry + audit sinks into tmp_path."""
    db_path = tmp_path / "ledger.db"
    reg_path = tmp_path / "run_registry.json"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Ledger: resolver is read at call time → patch it to the tmp db.
    monkeypatch.setattr(ledger_db, "_resolve_db_path", lambda: db_path)
    # Global registry: module-level paths captured at import → patch directly.
    monkeypatch.setattr(SR, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(SR, "LOCK_PATH", reg_path.with_suffix(".lock"))
    monkeypatch.setattr(SR, "RUNS_DIR", runs_dir)
    # Audit sinks → no-op (don't pollute real logs).
    monkeypatch.setattr(SR, "log_event", lambda **kw: None)
    monkeypatch.setattr(RB, "_audit_entry", lambda payload: None)

    # Seed the ledger: OLD live row + NEW row (mark_superseded requires NEW present).
    conn = sqlite3.connect(str(db_path))
    try:
        ledger_db.create_tables(conn)
        for rid in (OLD, NEW):
            conn.execute(
                'INSERT INTO master_filter ("run_id","symbol","strategy",'
                '"is_current","quarantined") VALUES (?,?,?,?,?)',
                (rid, SYMBOL, DIRECTIVE, 1, 0),
            )
        conn.commit()
    finally:
        conn.close()

    # Seed the global registry: OLD as a live COMPLETE run owning DIRECTIVE's identity.
    import json
    reg_path.write_text(
        json.dumps({OLD: {"run_id": OLD, "directive_hash": DIRECTIVE,
                          "status": "complete", "created_at": CREATED_AT}}),
        encoding="utf-8",
    )
    return {"db": db_path, "reg": reg_path}


def _ledger_row(db_path, run_id):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            'SELECT * FROM master_filter WHERE "run_id"=?', (run_id,)
        ).fetchone()
    finally:
        conn.close()


def test_operator_quarantine_releases_identity_end_to_end(isolated_state):
    db_path = isolated_state["db"]
    import json

    # --- PRE: the gates are LOCKED while OLD is a live complete run ---
    assert SR._get_directive_first_execution_timestamp(DIRECTIVE) is not None, \
        "precondition: a live complete run should anchor first-exec"
    assert GATE._can_reclaim_sweep(DIRECTIVE) is False, \
        "precondition: a live complete run should block sweep reclaim"

    # --- ACT: run the REAL operator workflow ---
    rc = RB.cmd_finalize(argparse.Namespace(
        old_run_id=OLD, new_run_id=NEW,
        reason="faithful re-validation: contaminated run, release identity",
        quarantine=True,
    ))
    assert rc == 0

    # --- ASSERT the five-point contract ---
    # (1) ledger row quarantined
    old_row = _ledger_row(db_path, OLD)
    assert old_row is not None, "(5) historical ledger row must survive"
    assert int(old_row["quarantined"]) == 1
    assert int(old_row["is_current"]) == 0
    assert old_row["superseded_by"] == NEW

    # (2) run_registry status quarantined
    reg = json.loads(isolated_state["reg"].read_text(encoding="utf-8"))
    assert reg[OLD]["status"] == "quarantined"

    # (3) first-exec ownership released
    assert SR._get_directive_first_execution_timestamp(DIRECTIVE) is None

    # (4) sweep ownership released
    assert GATE._can_reclaim_sweep(DIRECTIVE) is True

    # (5) historical run intact — run_id immutable, created_at preserved, nothing deleted
    assert OLD in reg
    assert reg[OLD]["run_id"] == OLD
    assert reg[OLD]["created_at"] == CREATED_AT


def test_non_quarantine_supersede_does_not_release_identity(isolated_state):
    """Guard: a plain supersede (no --quarantine) must NOT touch registry status,
    so identity ownership is preserved. Quarantine is the only releaser."""
    import json
    rc = RB.cmd_finalize(argparse.Namespace(
        old_run_id=OLD, new_run_id=NEW, reason="plain supersede, keep identity",
        quarantine=False,
    ))
    assert rc == 0
    reg = json.loads(isolated_state["reg"].read_text(encoding="utf-8"))
    assert reg[OLD]["status"] == "complete"            # registry untouched
    assert GATE._can_reclaim_sweep(DIRECTIVE) is False  # still owns the slot
    assert SR._get_directive_first_execution_timestamp(DIRECTIVE) is not None
