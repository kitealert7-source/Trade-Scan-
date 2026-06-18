"""Isolated tests for tools/state_lifecycle/retire_runs.py.

Every test runs against a temp ledger.db + temp state tree with
``config.path_authority.TRADE_SCAN_STATE`` monkeypatched — the real ledger and
the real TradeScan_State tree are never touched. The retire tool is destructive
(drops ledger rows, moves artifacts), so the dangerous paths are pinned hard:
never drops a live row, dry-run writes nothing, archive-before-drop, idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tools.state_lifecycle import retire_runs


_COINT_COLS = [
    "run_id", "directive_id", "is_current", "superseded_by", "backtests_path",
    "engine_version", "test_start", "test_end", "pair_a", "pair_b",
    "canonical_net_pct", "canonical_ret_dd", "canonical_max_dd_pct",
    "trades_total", "cycles_completed", "supersede_reason",
]

_MF_COLS = [
    "run_id", "strategy", "symbol", "is_current", "superseded_by",
    "profit_factor", "net_profit", "max_drawdown_pct", "trade_count",
]


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "TradeScan_State"
    for d in ("runs", "backtests", "retired", "quarantine", "logs"):
        (root / d).mkdir(parents=True, exist_ok=True)

    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", root, raising=False)
    # Keep the audit log inside the temp tree (don't write the real repo).
    monkeypatch.setattr(retire_runs, "_audit_log",
                        lambda: root / "logs" / "retire_audit.jsonl")

    class _S:
        pass

    s = _S()
    s.root = root
    s.db = root / "ledger.db"
    return s


def _make_table(db: Path, table: str, cols: list[str], rows: list[dict]) -> None:
    conn = sqlite3.connect(str(db))
    cols_sql = ", ".join(f'"{c}" TEXT' for c in cols)
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_sql})')
    for r in rows:
        ph = ", ".join("?" for _ in cols)
        conn.execute(
            f'INSERT INTO "{table}" ({", ".join(cols)}) VALUES ({ph})',
            tuple(r.get(c) for c in cols),
        )
    conn.commit()
    conn.close()


def _mk_artifacts(state, run_id: str, capsule: str):
    rh = state.root / "runs" / run_id
    rh.mkdir(parents=True, exist_ok=True)
    (rh / "directive.txt").write_text("x", encoding="utf-8")
    cap = state.root / "backtests" / capsule
    cap.mkdir(parents=True, exist_ok=True)
    (cap / "DIRECTIVE_SOURCE.txt").write_text("x", encoding="utf-8")
    return rh, cap


def _count(db: Path, table: str, run_id: str) -> int:
    conn = sqlite3.connect(str(db))
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0]
    conn.close()
    return n


# ── happy path ──────────────────────────────────────────────────────────────

def test_retire_happy_path_cointegration(state):
    rid = "aaaa1111bbbb2222cccc3333"
    cap = "90_PORT_AUDJPYESP35_15M_COINTREV_V3__E260127_AUDJPYESP35"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "90_PORT_AUDJPYESP35_15M_COINTREV_V3__E260127",
        "is_current": "0", "superseded_by": "newrun999",
        "backtests_path": f"backtests/{cap}", "engine_version": "1.5.8",
        "canonical_net_pct": "12.5", "canonical_ret_dd": "1.8",
        "canonical_max_dd_pct": "7.0", "trades_total": "30", "cycles_completed": "15",
        "pair_a": "AUDJPY", "pair_b": "ESP35", "supersede_reason": "ENGINE: v158->v1510",
    }])
    rh, capdir = _mk_artifacts(state, rid, cap)

    res = retire_runs.retire([rid], execute=True)
    assert len(res["retired"]) == 1 and res["retired"][0]["executed"]
    assert not res["errors"] and not res["refused"]

    # archived (with the metrics)
    arc = pd.read_parquet(state.root / "retired" / "retired_runs.parquet")
    assert rid in set(arc["run_id"].astype(str))
    row = arc[arc["run_id"].astype(str) == rid].iloc[0]
    assert float(row["net_pct"]) == 12.5
    assert row["source_sheet"] == "cointegration_sheet"
    assert row["pair_or_symbol"] == "AUDJPY/ESP35"

    # live row dropped
    assert _count(state.db, "cointegration_sheet", rid) == 0
    # artifacts moved to quarantine, gone from live
    assert not rh.exists() and not capdir.exists()
    assert (state.root / "quarantine" / "retired" / "runs" / rid).exists()
    assert (state.root / "quarantine" / "retired" / "backtests" / cap).exists()


def test_retire_master_filter_single_asset(state):
    rid = "ma000001"
    # Real convention: master_filter.strategy is the FULL symbol-suffixed id, and
    # the capsule is backtests/<strategy> (no extra _<symbol>).
    strat = "15_MR_FX_1H_PINBAR_S01_V1_P00_EURUSD"
    _make_table(state.db, "master_filter", _MF_COLS, [{
        "run_id": rid, "strategy": strat, "symbol": "EURUSD",
        "is_current": "0", "superseded_by": "succ", "profit_factor": "1.4",
        "net_profit": "250", "max_drawdown_pct": "8", "trade_count": "40",
    }])
    _mk_artifacts(state, rid, strat)
    res = retire_runs.retire([rid], execute=True)
    assert len(res["retired"]) == 1 and res["retired"][0]["executed"]
    assert _count(state.db, "master_filter", rid) == 0
    assert (state.root / "quarantine" / "retired" / "backtests" / strat).exists()
    arc = pd.read_parquet(state.root / "retired" / "retired_runs.parquet")
    assert arc.iloc[0]["pair_or_symbol"] == "EURUSD"
    assert arc.iloc[0]["directive_id"] == strat


# ── safety: dry-run + refusals ───────────────────────────────────────────────

def test_dry_run_writes_nothing(state):
    rid = "dddd4444"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "0",
        "superseded_by": "succ", "backtests_path": "backtests/X_S",
    }])
    rh, cap = _mk_artifacts(state, rid, "X_S")
    res = retire_runs.retire([rid], execute=False)
    assert res["dry_run"] and len(res["retired"]) == 1
    assert res["retired"][0]["executed"] is False
    assert not (state.root / "retired" / "retired_runs.parquet").exists()
    assert _count(state.db, "cointegration_sheet", rid) == 1
    assert rh.exists() and cap.exists()


def test_refuses_live_row_is_current_1(state):
    rid = "live0001"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "1", "superseded_by": None,
    }])
    res = retire_runs.retire([rid], execute=True)
    assert len(res["refused"]) == 1 and "not 0" in res["refused"][0]["why"]
    assert _count(state.db, "cointegration_sheet", rid) == 1  # NOT dropped


def test_refuses_null_is_current(state):
    rid = "null0001"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": None, "superseded_by": "s",
    }])
    res = retire_runs.retire([rid], execute=True)
    assert len(res["refused"]) == 1  # NULL is_current = current = refused
    assert _count(state.db, "cointegration_sheet", rid) == 1


def test_refuses_no_successor_then_force(state):
    rid = "nosucc01"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "0", "superseded_by": None,
        "backtests_path": "backtests/X_S",
    }])
    _mk_artifacts(state, rid, "X_S")
    res = retire_runs.retire([rid], execute=True, force=False)
    assert len(res["refused"]) == 1 and "successor" in res["refused"][0]["why"]
    assert _count(state.db, "cointegration_sheet", rid) == 1
    res2 = retire_runs.retire([rid], execute=True, force=True)
    assert len(res2["retired"]) == 1 and res2["retired"][0]["executed"]
    assert _count(state.db, "cointegration_sheet", rid) == 0


# ── idempotency + drift check ────────────────────────────────────────────────

def test_idempotent_rerun_after_drop(state):
    rid = "idem0001"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "0", "superseded_by": "s",
        "backtests_path": "backtests/X_S",
    }])
    _mk_artifacts(state, rid, "X_S")
    retire_runs.retire([rid], execute=True)
    # second pass: row gone -> skipped, no error, archive not duplicated
    res = retire_runs.retire([rid], execute=True)
    assert len(res["skipped"]) == 1 and not res["errors"]
    arc = pd.read_parquet(state.root / "retired" / "retired_runs.parquet")
    assert list(arc["run_id"].astype(str)).count(rid) == 1


def test_drift_check_counts_then_clears(state):
    rid = "drift001"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "0", "superseded_by": "s",
        "backtests_path": "backtests/X_S",
    }])
    _mk_artifacts(state, rid, "X_S")
    dc = retire_runs.drift_check()
    assert dc["count"] == 1 and dc["unretired"][0]["run_id"] == rid
    retire_runs.retire([rid], execute=True)
    dc2 = retire_runs.drift_check()
    assert dc2["count"] == 0


def test_drift_check_ignores_live_runs(state):
    # a live (is_current=1) run with artifacts must NOT show as un-retired drift
    rid = "livedrift"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "1", "superseded_by": None,
    }])
    _mk_artifacts(state, rid, "X_S")
    dc = retire_runs.drift_check()
    assert dc["count"] == 0


# ── real-schema coverage (the gaps the adversarial pass exploited) ───────────

# Real column sets (subset of the live schemas — verified via PRAGMA).
_BASKET_COLS = [
    "run_id", "directive_id", "basket_id", "trades_total", "final_realized_usd",
    "completed_at_utc", "backtests_path", "canonical_net_pct", "canonical_max_dd_pct",
    "canonical_ret_dd", "canonical_final_equity_usd", "cycles_completed",
    "is_current", "superseded_by", "supersede_reason",
]
_MF_REAL_COLS = [
    "run_id", "strategy", "symbol", "timeframe", "test_start", "test_end",
    "total_trades", "total_net_profit", "profit_factor", "max_drawdown",
    "max_dd_pct", "return_dd_ratio", "is_current", "superseded_by",
]


def test_basket_sheet_strips_raw_suffix(state):
    rid = "bbbb2222"
    capname = "90_PORT_GBPAUDUSDCHF_15M_COINTREV_V3__E002_GBPAUDUSDCHF"
    _make_table(state.db, "basket_sheet", _BASKET_COLS, [{
        "run_id": rid, "directive_id": "90_PORT_GBPAUDUSDCHF_15M_COINTREV_V3__E002",
        "basket_id": "GBPAUDUSDCHF", "is_current": "0", "superseded_by": "succ",
        "backtests_path": f"backtests/{capname}/raw/",  # REAL shape: ends in /raw/
        "canonical_net_pct": "59.9", "canonical_ret_dd": "1.84",
        "canonical_max_dd_pct": "32.5", "canonical_final_equity_usd": "1599",
        "trades_total": "44", "cycles_completed": "44",
    }])
    cap = state.root / "backtests" / capname
    (cap / "raw").mkdir(parents=True, exist_ok=True)
    (cap / "STRATEGY_CARD.md").write_text("x", encoding="utf-8")  # sibling of raw/
    (state.root / "runs" / rid).mkdir(parents=True, exist_ok=True)

    res = retire_runs.retire([rid], execute=True)
    assert len(res["retired"]) == 1 and res["retired"][0]["executed"] and not res["errors"]
    # the WHOLE capsule moved (not just raw/), so the sibling went too — nothing orphaned
    assert not cap.exists()
    moved = state.root / "quarantine" / "retired" / "backtests" / capname
    assert moved.exists() and (moved / "raw").exists() and (moved / "STRATEGY_CARD.md").exists()
    arc = pd.read_parquet(state.root / "retired" / "retired_runs.parquet")
    r = arc[arc["run_id"].astype(str) == rid].iloc[0]
    assert float(r["net_pct"]) == 59.9 and float(r["ret_dd"]) == 1.84
    assert r["pair_or_symbol"] == "GBPAUDUSDCHF" and r["source_sheet"] == "basket_sheet"


def test_basket_null_backtests_path_derives_capsule(state):
    rid = "bbbb3333"
    did = "90_PORT_EURJPYUSDJPY_15M_COINTREV_V3__E001"
    bid = "EURJPYUSDJPY"
    _make_table(state.db, "basket_sheet", _BASKET_COLS, [{
        "run_id": rid, "directive_id": did, "basket_id": bid,
        "is_current": "0", "superseded_by": "succ", "backtests_path": None,
        "canonical_net_pct": "10", "canonical_ret_dd": "1.0",
    }])
    cap = state.root / "backtests" / f"{did}_{bid}"
    cap.mkdir(parents=True, exist_ok=True)
    (cap / "x.txt").write_text("x", encoding="utf-8")
    (state.root / "runs" / rid).mkdir(parents=True, exist_ok=True)

    res = retire_runs.retire([rid], execute=True)
    assert len(res["retired"]) == 1 and not res["errors"]
    assert not cap.exists()  # derived capsule pruned, not left orphaned
    assert (state.root / "quarantine" / "retired" / "backtests" / f"{did}_{bid}").exists()


def test_master_filter_real_columns_no_double_suffix(state):
    rid = "ma222222"
    strat = "25_REV_XAUUSD_15M_LIQGRAB_S01_V1_P01_XAUUSD"  # ALREADY symbol-suffixed
    _make_table(state.db, "master_filter", _MF_REAL_COLS, [{
        "run_id": rid, "strategy": strat, "symbol": "XAUUSD", "timeframe": "15m",
        "test_start": "2024-01-02", "test_end": "2026-06-12", "is_current": "0",
        "superseded_by": "succ", "total_trades": "120", "total_net_profit": "1850",
        "profit_factor": "1.6", "max_dd_pct": "9.2", "return_dd_ratio": "2.1",
    }])
    cap = state.root / "backtests" / strat  # capsule = backtests/<strategy>
    (cap / "raw").mkdir(parents=True, exist_ok=True)
    decoy = state.root / "backtests" / f"{strat}_XAUUSD"  # double-suffix — must NOT be touched
    decoy.mkdir(parents=True, exist_ok=True)
    (state.root / "runs" / rid).mkdir(parents=True, exist_ok=True)

    res = retire_runs.retire([rid], execute=True)
    assert len(res["retired"]) == 1 and not res["errors"]
    assert not cap.exists()      # the real capsule was pruned
    assert decoy.exists()        # the unrelated double-suffix dir was NOT wrongly moved
    arc = pd.read_parquet(state.root / "retired" / "retired_runs.parquet")
    r = arc[arc["run_id"].astype(str) == rid].iloc[0]
    assert float(r["net_profit_usd"]) == 1850 and float(r["ret_dd"]) == 2.1
    assert float(r["trades"]) == 120 and float(r["profit_factor"]) == 1.6
    assert float(r["max_dd_pct"]) == 9.2


def test_refuses_fractional_is_current(state):
    # is_current=0.4 must NOT be treated as superseded (GUARD 1 now agrees with the
    # SQL guard) — refused cleanly, NOT archived, NOT dropped.
    rid = "frac0001"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "0.4", "superseded_by": "s",
        "backtests_path": "backtests/X_S",
    }])
    res = retire_runs.retire([rid], execute=True)
    assert len(res["refused"]) == 1 and not res["retired"]
    assert _count(state.db, "cointegration_sheet", rid) == 1            # not dropped
    assert not (state.root / "retired" / "retired_runs.parquet").exists()  # not archived


def test_corrupt_archive_fails_loud_no_drop(state):
    # A corrupt cold archive must abort (fail-fast) BEFORE any drop — never
    # overwrite the prior retirement history.
    rid = "newrun01"
    _make_table(state.db, "cointegration_sheet", _COINT_COLS, [{
        "run_id": rid, "directive_id": "X", "is_current": "0", "superseded_by": "s",
        "backtests_path": "backtests/X_S",
    }])
    arc = state.root / "retired" / "retired_runs.parquet"
    arc.parent.mkdir(parents=True, exist_ok=True)
    arc.write_bytes(b"not a parquet file")  # corrupt
    with pytest.raises(Exception):
        retire_runs.retire([rid], execute=True)
    assert _count(state.db, "cointegration_sheet", rid) == 1  # row NOT dropped


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
