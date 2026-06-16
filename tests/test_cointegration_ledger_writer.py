"""Tests for the cointegration ledger writer (P2).

Verifies the writer is a dumb, append-only, sink-only persister: it validates
the caller-provided row, fail-fasts on contract violations, enforces
append-only (provenance immutable), and never reads the screener DB.
"""
import sqlite3

import pytest

from tools.portfolio.cointegration_ledger_writer import (
    CointegrationLedgerError,
    append_cointegration_row,
)
from tools.portfolio.research_metrics import MetricsRegistryError


@pytest.fixture
def patched_state(tmp_path, monkeypatch):
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path)
    (tmp_path / "strategies").mkdir(exist_ok=True)
    return tmp_path


def _good_row(tmp_path, run_id="COINT0001"):
    """A complete, caller-supplied row (the writer computes nothing)."""
    (tmp_path / "backtests" / "rundir").mkdir(parents=True, exist_ok=True)
    return {
        "run_id": run_id,
        "directive_id": "90_PORT_COINT_EURUSDGER40_1D_S01_V1_P00",
        "pair_a": "EURUSD",
        "pair_b": "GER40",
        "timeframe": "1d",
        "lookback_days": 252,
        "test_start": "2025-01-01",
        "test_end": "2025-06-01",
        "completed_at_utc": "2026-05-28T12:00:00Z",
        "backtests_path": "backtests/rundir",
        "canonical_net_pct": 12.5,
        "canonical_max_dd_pct": 8.0,
        "canonical_ret_dd": 1.56,
        "canonical_final_equity_usd": 1125.0,
        "trades_total": 42,
        "methodology_version": "v1_raw_adf",
        "engine_version": "1.5.9",
    }


def _read(tmp_path, run_id):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        cur = conn.execute(
            "SELECT * FROM cointegration_sheet WHERE run_id = ?", (run_id,)
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
    finally:
        conn.close()
    return dict(zip(cols, row)) if row else None


def test_append_persists_row(patched_state):
    append_cointegration_row(_good_row(patched_state))
    got = _read(patched_state, "COINT0001")
    assert got is not None
    assert got["pair_a"] == "EURUSD"
    assert got["canonical_ret_dd"] == 1.56
    assert got["is_current"] == 1
    assert got["schema_version"] == "coint-1.0"
    assert got["enrichment_status"] == "complete"


def test_append_only_duplicate_raises(patched_state):
    append_cointegration_row(_good_row(patched_state))
    with pytest.raises(CointegrationLedgerError, match="[Aa]ppend-only"):
        append_cointegration_row(_good_row(patched_state))


def test_missing_required_field_raises(patched_state):
    row = _good_row(patched_state)
    del row["canonical_ret_dd"]
    with pytest.raises(CointegrationLedgerError, match="missing required"):
        append_cointegration_row(row)


def test_missing_methodology_version_raises(patched_state):
    """C2 invariant: methodology_version is mandatory on every corpus row."""
    row = _good_row(patched_state)
    del row["methodology_version"]
    with pytest.raises(CointegrationLedgerError, match="missing required"):
        append_cointegration_row(row)


def test_missing_backtest_folder_raises(patched_state):
    row = _good_row(patched_state)
    row["backtests_path"] = "backtests/does_not_exist"
    with pytest.raises(CointegrationLedgerError, match="does not exist"):
        append_cointegration_row(row)


def test_unknown_column_raises(patched_state):
    row = _good_row(patched_state)
    row["totally_made_up"] = 1
    with pytest.raises(CointegrationLedgerError, match="unknown column"):
        append_cointegration_row(row)


def test_metrics_json_unknown_key_raises(patched_state):
    row = _good_row(patched_state)
    row["metrics_json"] = '{"tail.worst_trade_pct": -3.2}'  # not registered in v1
    with pytest.raises(MetricsRegistryError, match="unknown metric key"):
        append_cointegration_row(row)


def test_writer_is_sink_only_no_screener_reference():
    """Ruthless sink-only guard: the writer must not reference the screener DB."""
    import inspect
    import tools.portfolio.cointegration_ledger_writer as w
    src = inspect.getsource(w)
    assert "cointegration_db" not in src
    assert "SYSTEM_FACTORS" not in src


def test_export_mps_emits_cointegration_tab(patched_state):
    """End-to-end: a written row surfaces as the curated Cointegration tab."""
    import pandas as pd
    from tools.ledger_db import export_mps
    from tools.portfolio.cointegration_view import COINTEGRATION_VIEW_COLUMNS

    append_cointegration_row(_good_row(patched_state))
    out = export_mps()
    xl = pd.ExcelFile(out)
    assert "Cointegration" in xl.sheet_names
    df = pd.read_excel(out, sheet_name="Cointegration")
    assert list(df.columns) == COINTEGRATION_VIEW_COLUMNS
    assert len(df) == 1
    assert df.iloc[0]["pair"] == "EURUSD / GER40"
    assert df.iloc[0]["backtest"] == "rundir"


# --- Identity-preserving refresh (cointegration pilot, 2026-06-07) -----------
# A refresh re-runs an existing directive with a NEW run_id; the writer marks
# any prior is_current=1 row for the SAME directive_id as superseded (flip,
# never delete) using the dormant supersession columns. Scope: cointegration
# only; no master_filter / mark_superseded / quarantine involvement.

_DIRECTIVE_ID = "90_PORT_COINT_EURUSDGER40_1D_S01_V1_P00"  # _good_row's directive_id


def _count_current(tmp_path, directive_id):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM cointegration_sheet "
            "WHERE directive_id = ? AND is_current = 1",
            (directive_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def test_refresh_supersedes_prior_same_directive(patched_state):
    """Second append for the same directive_id (new run_id) flips the prior row
    is_current=0 (superseded_by the new run, kind='re-run'), retains it, and
    leaves exactly one current row."""
    append_cointegration_row(_good_row(patched_state, run_id="COINTold1"))
    append_cointegration_row(_good_row(patched_state, run_id="COINTnew2"))

    old, new = _read(patched_state, "COINTold1"), _read(patched_state, "COINTnew2")
    assert old is not None, "prior row must be RETAINED (flip, never delete)"
    assert old["is_current"] == 0
    assert old["superseded_by"] == "COINTnew2"
    assert old["supersede_kind"] == "re-run"
    assert old["superseded_at"]                      # timestamp set
    assert new["is_current"] == 1
    assert new["superseded_by"] is None
    assert _count_current(patched_state, _DIRECTIVE_ID) == 1


def test_first_append_leaves_no_supersession(patched_state):
    """A directive's first run has no prior to flip: is_current=1 with the
    supersession fields untouched (no spurious flip on a clean first append)."""
    append_cointegration_row(_good_row(patched_state, run_id="COINTfirst"))
    row = _read(patched_state, "COINTfirst")
    assert row["is_current"] == 1
    assert row["superseded_by"] is None
    assert row["superseded_at"] is None


def test_distinct_directives_not_cross_superseded(patched_state):
    """Refresh-supersede is scoped to the SAME directive_id: a run of a
    different directive must NOT flip another directive's current row."""
    r1 = _good_row(patched_state, run_id="COINTdirA")
    r1["directive_id"] = "90_PORT_COINT_AAA_1D_S01_V1_P00"
    r2 = _good_row(patched_state, run_id="COINTdirB")
    r2["directive_id"] = "90_PORT_COINT_BBB_1D_S01_V1_P00"
    append_cointegration_row(r1)
    append_cointegration_row(r2)
    assert _read(patched_state, "COINTdirA")["is_current"] == 1
    assert _read(patched_state, "COINTdirB")["is_current"] == 1
