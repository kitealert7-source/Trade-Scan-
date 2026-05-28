"""Tests for tools/window_validity_gate.check_window_validity (Task B).

Continuous-span semantics (operator-locked 2026-05-28):
  - aligned = regime == 'cointegrated' ONLY ('breaking'/'broken' are not)
  - pass iff test window fully inside ANY single continuous cointegrated span
    (the any-span widening, 2026-05-28: not restricted to the latest span;
    provenance reports the CONTAINING span). A straddle/overrun still rejects.
  - no fractions, no smoothing, no interpolation, no tolerance

Fixtures use a synthetic temp SQLite DB with a minimal cointegration_daily
table (only the columns the gate SELECTs). A live-DB invariant guard asserts
the (pair, lookback) -> unique tf assumption the gate relies on.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

import tools.window_validity_gate as gate
from tools.window_validity_gate import (
    WindowValidityGateError,
    WindowValidityResult,
    check_window_validity,
    evaluate_window_validity,
    _continuous_cointegrated_spans,
)


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def synthetic_db(tmp_path, monkeypatch):
    """Create a temp cointegration.db with a minimal schema; patch DB_PATH."""
    db = tmp_path / "cointegration.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE cointegration_daily ("
        " as_of TEXT, pair_a TEXT, pair_b TEXT, tf TEXT,"
        " lookback_days INTEGER, regime TEXT)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(gate, "DB_PATH", db)

    def _insert(pair_a, pair_b, lookback, rows, tf="1d"):
        c = sqlite3.connect(str(db))
        c.executemany(
            "INSERT INTO cointegration_daily "
            "(as_of, pair_a, pair_b, tf, lookback_days, regime) "
            "VALUES (?,?,?,?,?,?)",
            [(d, pair_a, pair_b, tf, lookback, r) for d, r in rows],
        )
        c.commit()
        c.close()

    return _insert


def _write_directive(
    path: Path,
    *,
    symbols: list[str] | None,
    lookback: int | None,
    start: str | None = "2025-01-01",
    end: str | None = "2025-06-01",
    override: str | None = None,
) -> Path:
    doc: dict = {"test": {}}
    if start is not None:
        doc["test"]["start_date"] = start
    if end is not None:
        doc["test"]["end_date"] = end
    basket: dict = {}
    if symbols is not None:
        basket["legs"] = [{"symbol": s} for s in symbols]
    if lookback is not None:
        cj: dict = {"lookback_days": lookback}
        if override is not None:
            cj["methodology_override"] = override
        basket["cointegration_join"] = cj
    if basket:
        doc["basket"] = basket
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def _daily(start: str, regimes: list[str]) -> list[tuple[str, str]]:
    """Build a daily (as_of, regime) series starting at `start`."""
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=i)).isoformat(), r) for i, r in enumerate(regimes)]


# --- span algorithm unit tests ---------------------------------------------

def test_spans_basic_runs():
    series = _daily("2025-01-01", [
        "cointegrated", "cointegrated", "broken",
        "cointegrated", "cointegrated", "cointegrated",
    ])
    spans = _continuous_cointegrated_spans(series)
    assert len(spans) == 2
    assert spans[-1].start == "2025-01-04" and spans[-1].end == "2025-01-06"
    assert spans[-1].n_rows == 3


def test_breaking_is_not_aligned():
    """'breaking' must split a span — operator-locked, critical."""
    series = _daily("2025-01-01", [
        "cointegrated", "breaking", "cointegrated",
    ])
    spans = _continuous_cointegrated_spans(series)
    assert len(spans) == 2  # breaking broke the run, not smoothed over


# --- gate behavior ---------------------------------------------------------

def test_window_inside_latest_span_passes(tmp_path, synthetic_db):
    synthetic_db("EURUSD", "USDJPY", 252,
                 _daily("2024-01-01", ["cointegrated"] * 400))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-03-01", end="2024-10-01")
    check_window_validity(d)  # no raise


def test_window_starts_before_span_rejects(tmp_path, synthetic_db):
    # aligned span: 2024-06-01 .. 2024-12-31; window starts before it
    synthetic_db("EURUSD", "USDJPY", 252,
                 _daily("2024-01-01", ["broken"] * 152 + ["cointegrated"] * 214))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-03-01", end="2024-09-01")
    with pytest.raises(WindowValidityGateError, match="before the aligned span"):
        check_window_validity(d)


def test_window_ends_after_span_rejects(tmp_path, synthetic_db):
    # aligned span ends 2024-06-30, then breaks; window extends past it
    synthetic_db("EURUSD", "USDJPY", 252,
                 _daily("2024-01-01", ["cointegrated"] * 181 + ["broken"] * 100))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-02-01", end="2024-09-01")
    with pytest.raises(WindowValidityGateError, match="after the aligned span"):
        check_window_validity(d)


def test_window_spanning_a_break_rejects(tmp_path, synthetic_db):
    # two cointegrated spans separated by a break; window straddles the break
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01",
                 ["cointegrated"] * 100 + ["broken"] * 50 + ["cointegrated"] * 100))
    # window starts in span 1, ends in span 2 -> not contained in LATEST span
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-02-01", end="2024-08-01")
    with pytest.raises(WindowValidityGateError):
        check_window_validity(d)


def test_window_inside_earlier_span_passes(tmp_path, synthetic_db):
    """ANY-SPAN: a window inside an EARLIER (non-latest) cointegrated span
    passes, and provenance reports THAT span (not the latest)."""
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01",
                 ["cointegrated"] * 100 + ["broken"] * 50 + ["cointegrated"] * 100))
    # span 1 = 2024-01-01 .. 2024-04-09 (100 rows); window sits inside it
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-01-15", end="2024-03-01")
    check_window_validity(d)  # no raise -- earlier span is admissible
    r = evaluate_window_validity(d)
    assert r.status == "PASS"
    assert r.span_start == "2024-01-01"   # the EARLIER span, not the latest
    assert r.span_end == "2024-04-09"
    assert r.continuous_span_obs == 100
    assert r.fragment_count == 2          # both spans still counted
    assert r.regime_state == "cointegrated"


def test_reject_suggestion_names_nearest_span(tmp_path, synthetic_db):
    """A window in the GAP between two spans is contained by neither -> reject,
    with a suggestion naming a real span."""
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01",
                 ["cointegrated"] * 100 + ["broken"] * 50 + ["cointegrated"] * 100))
    # gap = 2024-04-10 .. 2024-05-29; window falls inside the gap
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-04-20", end="2024-05-20")
    with pytest.raises(WindowValidityGateError) as exc:
        check_window_validity(d)
    msg = str(exc.value)
    assert "Suggested directive window" in msg
    assert "2024-09-06" in msg  # nearest/fallback span end


def test_pair_order_normalization(tmp_path, synthetic_db):
    # DB stores canonical sorted order EURUSD<USDJPY; directive lists reversed
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01", ["cointegrated"] * 400))
    d = _write_directive(tmp_path / "d.txt", symbols=["USDJPY", "EURUSD"],
                         lookback=252, start="2024-03-01", end="2024-10-01")
    check_window_validity(d)  # no raise — canonicalization found the rows


def test_no_rows_for_pair_rejects(tmp_path, synthetic_db):
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01", ["cointegrated"] * 10))
    d = _write_directive(tmp_path / "d.txt", symbols=["GBPUSD", "AUDUSD"],
                         lookback=252, start="2024-03-01", end="2024-10-01")
    with pytest.raises(WindowValidityGateError, match="no cointegration history"):
        check_window_validity(d)


def test_override_admits_with_warn(tmp_path, synthetic_db, capsys):
    synthetic_db("EURUSD", "USDJPY", 252,
                 _daily("2024-01-01", ["broken"] * 200))  # never aligned
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-03-01", end="2024-09-01",
                         override="testing a deliberate out-of-regime hypothesis")
    check_window_validity(d)  # no raise
    out = capsys.readouterr().out
    assert "METHODOLOGY_OVERRIDE" in out
    assert "testing a deliberate" in out


def test_no_cointegration_join_is_noop(tmp_path, synthetic_db):
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=None, start="2024-03-01", end="2024-10-01")
    check_window_validity(d)  # no raise — gate does not apply


def test_non_two_symbol_basket_is_noop(tmp_path, synthetic_db):
    d = _write_directive(tmp_path / "d.txt",
                         symbols=["EURUSD", "USDJPY", "GBPUSD"],
                         lookback=252, start="2024-03-01", end="2024-10-01")
    check_window_validity(d)  # no raise — pairwise construct only


def test_missing_db_raises_not_overridable(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "DB_PATH", tmp_path / "does_not_exist.db")
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-03-01", end="2024-10-01",
                         override="should not save us from a missing DB")
    with pytest.raises(WindowValidityGateError, match="not found"):
        check_window_validity(d)


# --- live-DB invariant guard ------------------------------------------------

def test_live_db_lookback_determines_tf():
    """The gate keys queries on (pair, lookback) and relies on lookback ->
    unique tf. If the screener ever populates both tfs at one lookback, the
    regime series would mix tfs and the span computation would be wrong.
    This guard fails loudly if that invariant breaks."""
    from tools.cointegration_db import SQLITE_DB, TABLE_NAME
    if not SQLITE_DB.exists():
        pytest.skip("live cointegration.db not present")
    conn = sqlite3.connect(str(SQLITE_DB))
    try:
        violators = conn.execute(
            f"SELECT pair_a, pair_b, lookback_days, COUNT(DISTINCT tf) ntf "
            f"FROM {TABLE_NAME} GROUP BY pair_a, pair_b, lookback_days "
            f"HAVING ntf > 1 LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    assert not violators, (
        f"(pair, lookback) -> multiple tf in live DB: {violators}. "
        f"window_validity_gate queries on (pair, lookback) and assumes a "
        f"unique tf; add tf to the query if this invariant no longer holds."
    )


# --- evaluate_window_validity (non-raising core + provenance) --------------

def test_evaluate_not_applicable_without_cointegration_join(tmp_path, synthetic_db):
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=None)
    r = evaluate_window_validity(d)
    assert isinstance(r, WindowValidityResult)
    assert r.applies is False
    assert r.status == "NOT_APPLICABLE"
    assert r.ledger_window_status == "N/A"


def test_evaluate_pass_populates_provenance(tmp_path, synthetic_db):
    synthetic_db("EURUSD", "USDJPY", 252,
                 _daily("2024-01-01", ["cointegrated"] * 400))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-03-01", end="2024-10-01")
    r = evaluate_window_validity(d)
    assert r.status == "PASS"
    assert r.ledger_window_status == "PASS"
    assert r.span_start == "2024-01-01"
    assert r.continuous_span_obs == 400
    assert r.fragment_count == 1
    assert r.pct_cointegrated == 1.0
    assert r.regime_state == "cointegrated"
    assert r.reject_reason is None


def test_evaluate_reject_keeps_provenance_and_does_not_raise(tmp_path, synthetic_db):
    # two cointegrated spans separated by a break; window straddles -> reject
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01",
                 ["cointegrated"] * 100 + ["broken"] * 50 + ["cointegrated"] * 100))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-02-01", end="2024-08-01")
    r = evaluate_window_validity(d)   # must NOT raise
    assert r.status == "REJECT"
    assert r.reject_reason is not None
    assert r.fragment_count == 2
    assert r.ledger_window_status == "N/A"  # rejected, no override


def test_evaluate_override_maps_to_override_status(tmp_path, synthetic_db):
    synthetic_db("EURUSD", "USDJPY", 252, _daily("2024-01-01", ["broken"] * 200))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-03-01", end="2024-09-01",
                         override="deliberate out-of-regime probe")
    r = evaluate_window_validity(d)
    assert r.status == "REJECT"
    assert r.override_reason == "deliberate out-of-regime probe"
    assert r.ledger_window_status == "OVERRIDE"


def test_evaluate_pct_cointegrated_fraction(tmp_path, synthetic_db):
    # 100 cointegrated of 200 total -> 0.5; latest span is the trailing run
    synthetic_db("EURUSD", "USDJPY", 252,
                 _daily("2024-01-01", ["broken"] * 100 + ["cointegrated"] * 100))
    d = _write_directive(tmp_path / "d.txt", symbols=["EURUSD", "USDJPY"],
                         lookback=252, start="2024-05-01", end="2024-06-01")
    r = evaluate_window_validity(d)
    assert r.pct_cointegrated == 0.5
    assert r.fragment_count == 1
    assert r.regime_state == "cointegrated"
