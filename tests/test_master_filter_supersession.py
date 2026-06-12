"""Phase-0 master_filter supersession enforcement (governance "Option C").

These tests exercise tools/ledger_db.upsert_master_filter_df's supersede_for
keyword against a TEMP sqlite ledger only — config.path_authority.TRADE_SCAN_STATE
is monkeypatched per test so the real ledger.db is never touched.

Contract under test (per (strategy, symbol) scope, run_id != new):
  * first run               -> 1 current row, no supersede.
  * DECLARED rerun (True)   -> prior is_current flipped to 0 / superseded_by=new;
                               the new run is the only current row.
  * UNDECLARED collision    -> raises MasterFilterCurrencyError, NOTHING mutated.
  * same run_id re-write     -> idempotent no-op (run_id != new excludes it).
  * multi-symbol            -> only the colliding (strategy, symbol) superseded.
  * partial rerun           -> old {A,B}, new {A} -> old A superseded, old B current.
  * atomicity               -> insert raises mid-way -> no supersession persists.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tools.ledger_db import (
    MASTER_FILTER_COLUMNS,
    MasterFilterCurrencyError,
    _connect,
    create_tables,
    upsert_master_filter_df,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Temp ledger.db with master_filter created. Returns a connection.

    Patches config.path_authority.TRADE_SCAN_STATE so _resolve_db_path() (used
    by _connect) points at the temp tree — the real ledger.db is untouched.
    """
    state = tmp_path / "TradeScan_State"
    state.mkdir(parents=True, exist_ok=True)
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", state, raising=False)

    conn = _connect()
    create_tables(conn)
    yield conn
    conn.close()


def _row(run_id: str, strategy: str, symbol: str, **extra) -> dict:
    """Build a master_filter row dict (only identity cols matter for the test).

    Deliberately omits is_current/superseded_* so a fresh insert lands at the
    DB default (is_current=1) — mirrors stage3_compiler, which does not write
    the supersession columns.
    """
    base = {c: None for c in MASTER_FILTER_COLUMNS}
    base.update({"run_id": run_id, "strategy": strategy, "symbol": symbol})
    base.update(extra)
    # Drop the supersession columns so the INSERT relies on DB defaults.
    for c in ("is_current", "superseded_by", "superseded_at",
              "supersede_reason", "quarantined"):
        base.pop(c, None)
    return base


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _fetch(conn, run_id, symbol):
    return conn.execute(
        'SELECT "is_current", "superseded_by", "superseded_at", '
        '"supersede_reason" FROM master_filter '
        'WHERE "run_id" = ? AND "symbol" = ?',
        (run_id, symbol),
    ).fetchone()


def _current_run_ids(conn, strategy, symbol):
    rows = conn.execute(
        'SELECT "run_id" FROM master_filter '
        'WHERE "strategy" = ? AND "symbol" = ? '
        'AND ("is_current" = 1 OR "is_current" IS NULL)',
        (strategy, symbol),
    ).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# (a) first run -> 1 current, no supersede
# ---------------------------------------------------------------------------

def test_first_run_lands_current_no_supersede(db):
    df = _df([_row("RUN_A", "STRAT1", "EURUSD")])
    upsert_master_filter_df(db, df, supersede_for={"RUN_A": False})

    row = _fetch(db, "RUN_A", "EURUSD")
    assert row["is_current"] == 1
    assert row["superseded_by"] is None
    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_A"}


# ---------------------------------------------------------------------------
# (b) DECLARED rerun -> prior flipped, new is the only current
# ---------------------------------------------------------------------------

def test_declared_rerun_supersedes_prior(db):
    # Prior run lands current.
    upsert_master_filter_df(db, _df([_row("RUN_A", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_A": False})
    # New declared rerun for same (strategy, symbol).
    upsert_master_filter_df(db, _df([_row("RUN_B", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_B": True})

    old = _fetch(db, "RUN_A", "EURUSD")
    assert old["is_current"] == 0
    assert old["superseded_by"] == "RUN_B"
    assert old["superseded_at"] is not None
    assert old["supersede_reason"] == "AUTO_SUPERSEDE: declared rerun (stage3)"

    new = _fetch(db, "RUN_B", "EURUSD")
    assert new["is_current"] == 1
    assert new["superseded_by"] is None

    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_B"}


# ---------------------------------------------------------------------------
# (c) UNDECLARED collision -> raises, NOTHING mutated
# ---------------------------------------------------------------------------

def test_undeclared_collision_raises_and_no_mutation(db):
    upsert_master_filter_df(db, _df([_row("RUN_A", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_A": False})

    with pytest.raises(MasterFilterCurrencyError) as exc:
        upsert_master_filter_df(db, _df([_row("RUN_B", "STRAT1", "EURUSD")]),
                                supersede_for={"RUN_B": False})

    # The exception lists the colliding identity tuple.
    msg = str(exc.value)
    assert "STRAT1" in msg and "EURUSD" in msg
    assert "RUN_A" in msg and "RUN_B" in msg

    # The raise happens BEFORE conn.commit(), so the caller rolls back the
    # uncommitted transaction (mirrors stage3 / _connect callers on exception).
    db.rollback()

    # Nothing mutated: prior still current, and the new row was never committed.
    old = _fetch(db, "RUN_A", "EURUSD")
    assert old["is_current"] == 1
    assert old["superseded_by"] is None
    assert _fetch(db, "RUN_B", "EURUSD") is None
    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_A"}


# ---------------------------------------------------------------------------
# (d) same run_id re-write -> idempotent no-op
# ---------------------------------------------------------------------------

def test_same_run_id_rewrite_is_noop(db):
    upsert_master_filter_df(db, _df([_row("RUN_A", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_A": False})
    # Re-write the SAME run_id (e.g. a stage3 re-export). run_id != new
    # excludes the run's own rows from the supersede scan -> no self-supersede.
    upsert_master_filter_df(db, _df([_row("RUN_A", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_A": True})

    row = _fetch(db, "RUN_A", "EURUSD")
    assert row["is_current"] == 1
    assert row["superseded_by"] is None
    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_A"}


# ---------------------------------------------------------------------------
# (e) multi-symbol: supersede only the colliding (strategy, symbol) pairs
# ---------------------------------------------------------------------------

def test_multi_symbol_supersede_only_colliding_pairs(db):
    # Old run covers EURUSD + GBPUSD.
    upsert_master_filter_df(
        db,
        _df([_row("RUN_A", "STRAT1", "EURUSD"),
             _row("RUN_A", "STRAT1", "GBPUSD")]),
        supersede_for={"RUN_A": False},
    )
    # Unrelated strategy on EURUSD must NOT be touched.
    upsert_master_filter_df(db, _df([_row("RUN_X", "STRAT2", "EURUSD")]),
                            supersede_for={"RUN_X": False})

    # Declared rerun covers BOTH of STRAT1's symbols.
    upsert_master_filter_df(
        db,
        _df([_row("RUN_B", "STRAT1", "EURUSD"),
             _row("RUN_B", "STRAT1", "GBPUSD")]),
        supersede_for={"RUN_B": True},
    )

    assert _fetch(db, "RUN_A", "EURUSD")["is_current"] == 0
    assert _fetch(db, "RUN_A", "GBPUSD")["is_current"] == 0
    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_B"}
    assert _current_run_ids(db, "STRAT1", "GBPUSD") == {"RUN_B"}
    # Unrelated strategy untouched.
    assert _current_run_ids(db, "STRAT2", "EURUSD") == {"RUN_X"}
    assert _fetch(db, "RUN_X", "EURUSD")["is_current"] == 1


# ---------------------------------------------------------------------------
# (f) PARTIAL rerun: old {A,B}, new {A} -> old A superseded, old B still current
# ---------------------------------------------------------------------------

def test_partial_rerun_leaves_uncovered_symbol_current(db):
    upsert_master_filter_df(
        db,
        _df([_row("RUN_A", "STRAT1", "EURUSD"),
             _row("RUN_A", "STRAT1", "GBPUSD")]),
        supersede_for={"RUN_A": False},
    )
    # Declared rerun covers ONLY EURUSD.
    upsert_master_filter_df(db, _df([_row("RUN_B", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_B": True})

    # EURUSD superseded, GBPUSD (uncovered) stays current under the OLD run.
    assert _fetch(db, "RUN_A", "EURUSD")["is_current"] == 0
    assert _fetch(db, "RUN_A", "GBPUSD")["is_current"] == 1
    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_B"}
    assert _current_run_ids(db, "STRAT1", "GBPUSD") == {"RUN_A"}


# ---------------------------------------------------------------------------
# (g) atomicity: insert raises mid-way -> no supersession persists
# ---------------------------------------------------------------------------

class _FailingConn:
    """Proxy over a real sqlite3.Connection that fails the Nth INSERT.

    sqlite3.Connection.execute is a read-only C attribute (can't monkeypatch),
    so we wrap it. upsert_master_filter_df only uses .execute() and .commit();
    everything else delegates. This lets us simulate a mid-write INSERT failure
    and assert the supersession UPDATE (which runs AFTER the insert loop) never
    fired and nothing committed.
    """

    def __init__(self, real, fail_on_insert_n):
        self._real = real
        self._fail_on = fail_on_insert_n
        self._insert_count = 0

    def execute(self, sql, *args, **kwargs):
        if sql.strip().upper().startswith("INSERT"):
            self._insert_count += 1
            if self._insert_count == self._fail_on:
                raise sqlite3.OperationalError("simulated mid-insert failure")
        return self._real.execute(sql, *args, **kwargs)

    def commit(self):
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_atomicity_insert_failure_leaves_no_supersession(db):
    upsert_master_filter_df(db, _df([_row("RUN_A", "STRAT1", "EURUSD")]),
                            supersede_for={"RUN_A": False})

    # Fail on the 2nd INSERT of the new batch — after the 1st row inserts but
    # before the loop completes, so commit() is never reached and the
    # supersession block never runs.
    failing = _FailingConn(db, fail_on_insert_n=2)
    df = _df([_row("RUN_B", "STRAT1", "EURUSD"),
              _row("RUN_B", "STRAT1", "GBPUSD")])
    with pytest.raises(sqlite3.OperationalError):
        upsert_master_filter_df(failing, df, supersede_for={"RUN_B": True})

    # Caller rolls back the uncommitted transaction.
    db.rollback()

    # Prior run never superseded — the failed batch did not commit.
    old = _fetch(db, "RUN_A", "EURUSD")
    assert old["is_current"] == 1
    assert old["superseded_by"] is None
    # And the partial new rows did not persist.
    assert _fetch(db, "RUN_B", "EURUSD") is None
    assert _current_run_ids(db, "STRAT1", "EURUSD") == {"RUN_A"}


# ---------------------------------------------------------------------------
# _read_rerun_authorized — the security-critical authorization signal.
# It gates AUTO-SUPERSEDE vs FAIL-LOUD, so its default-False-on-any-ambiguity
# contract must be locked directly (not only via the enforcement tests).
# ---------------------------------------------------------------------------

@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    """Temp runs/ tree with stage3_compiler.RUNS_DIR pointed at it."""
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    import tools.stage3_compiler as s3
    monkeypatch.setattr(s3, "RUNS_DIR", runs, raising=False)
    return runs


def _write_directive(runs, run_id: str, text: str) -> None:
    d = runs / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "directive.txt").write_text(text, encoding="utf-8")


def test_rerun_auth_absent_snapshot_is_false(runs_dir):
    """No directive.txt at all -> undeclared (False)."""
    from tools.stage3_compiler import _read_rerun_authorized
    assert _read_rerun_authorized("NO_SUCH_RUN") is False


def test_rerun_auth_malformed_yaml_is_false(runs_dir):
    """Unparseable YAML -> swallowed, undeclared (False) — never authorizes."""
    from tools.stage3_compiler import _read_rerun_authorized
    _write_directive(runs_dir, "RUN_BAD", "test: [unclosed\n  : ::: not yaml")
    assert _read_rerun_authorized("RUN_BAD") is False


def test_rerun_auth_non_dict_root_is_false(runs_dir):
    """YAML parses to a scalar/list, not a mapping -> False."""
    from tools.stage3_compiler import _read_rerun_authorized
    _write_directive(runs_dir, "RUN_LIST", "- a\n- b\n")
    assert _read_rerun_authorized("RUN_LIST") is False


def test_rerun_auth_non_dict_test_block_is_false(runs_dir):
    """test: present but not a mapping -> False."""
    from tools.stage3_compiler import _read_rerun_authorized
    _write_directive(runs_dir, "RUN_T", "test: not_a_mapping\n")
    assert _read_rerun_authorized("RUN_T") is False


def test_rerun_auth_missing_key_is_false(runs_dir):
    """test: block without repeat_override_reason -> False."""
    from tools.stage3_compiler import _read_rerun_authorized
    _write_directive(runs_dir, "RUN_M", "test:\n  name: foo\n  strategy: bar\n")
    assert _read_rerun_authorized("RUN_M") is False


def test_rerun_auth_empty_reason_is_false(runs_dir):
    """Empty repeat_override_reason is falsy -> NOT a declaration (False)."""
    from tools.stage3_compiler import _read_rerun_authorized
    _write_directive(runs_dir, "RUN_E", 'test:\n  repeat_override_reason: ""\n')
    assert _read_rerun_authorized("RUN_E") is False


def test_rerun_auth_present_reason_is_true(runs_dir):
    """Non-empty repeat_override_reason -> declared rerun (True)."""
    from tools.stage3_compiler import _read_rerun_authorized
    _write_directive(
        runs_dir, "RUN_OK",
        'test:\n  repeat_override_reason: "[RERUN:DATA_FRESH] more bars available"\n',
    )
    assert _read_rerun_authorized("RUN_OK") is True
