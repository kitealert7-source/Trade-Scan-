"""Tests for P5: reenrich (recompute from retained substrate) + retention guard.

reenrich must update ONLY derived metrics (+ metrics_fn_version), verify the
substrate sha256, refuse on substrate change / loss, and leave provenance
immutable. The retention guard must surface current coint runs (with basket_id
recovered from the folder) so the cleanup keeps their substrate.
"""
import hashlib
import sqlite3

import pytest

from tools.portfolio.cointegration_ledger_writer import append_cointegration_row
from tools.portfolio.cointegration_schema import METRICS_FN_VERSION
from tools.reenrich_cointegration import ReenrichError, reenrich_cointegration_row


@pytest.fixture
def patched_state(tmp_path, monkeypatch):
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path)
    (tmp_path / "strategies").mkdir(exist_ok=True)
    return tmp_path


_FAKE_CM = {
    "net_pct": 22.2, "max_dd_pct": 9.0, "max_dd_pct_vs_stake": 7.0,
    "ret_dd": 2.47, "final_equity_usd": 1222.0,
    "cycle_win_rate_pct": 60.0, "cycles_completed": 14,
}


def _make_run(tmp_path, run_id="COINTR1", directive_id="DIR", basket_id="H2"):
    folder = f"{directive_id}_{basket_id}"
    raw = tmp_path / "backtests" / folder / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    pq = raw / "results_basket_per_bar.parquet"
    pq.write_bytes(b"dummy-parquet-bytes")
    sha = hashlib.sha256(pq.read_bytes()).hexdigest()
    append_cointegration_row({
        "run_id": run_id, "directive_id": directive_id,
        "pair_a": "EURUSD", "pair_b": "GER40", "timeframe": "1d",
        "lookback_days": 252, "test_start": "2025-01-01", "test_end": "2025-06-01",
        "completed_at_utc": "2026-05-28T00:00:00Z",
        "backtests_path": f"backtests/{folder}",
        "parquet_sha256": sha, "stake_usd": 1000.0,
        "canonical_net_pct": 1.0, "canonical_max_dd_pct": 1.0,
        "canonical_ret_dd": 1.0, "canonical_final_equity_usd": 1010.0,
        "trades_total": 5,
        "methodology_version": "v1_raw_adf",
        "engine_version": "1.5.9",
    })
    return run_id, pq


def _read(tmp_path, run_id):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        cur = conn.execute("SELECT * FROM cointegration_sheet WHERE run_id = ?", (run_id,))
        cols = [d[0] for d in cur.description]
        r = cur.fetchone()
    finally:
        conn.close()
    return dict(zip(cols, r)) if r else None


def _patch_cm(monkeypatch):
    # canonical_metrics is re-exported at the package level, which shadows the
    # submodule for attribute access. reenrich does
    # `from ...canonical_metrics import canonical_metrics`, which resolves the
    # name on the SUBMODULE -- reach it via sys.modules (the real module object).
    import sys
    import tools.basket_hypothesis.canonical_metrics  # noqa: F401 (ensure loaded)
    mod = sys.modules["tools.basket_hypothesis.canonical_metrics"]
    monkeypatch.setattr(mod, "canonical_metrics", lambda p, s: dict(_FAKE_CM))


def test_reenrich_updates_only_metrics(patched_state, monkeypatch):
    run_id, _ = _make_run(patched_state)
    _patch_cm(monkeypatch)
    out = reenrich_cointegration_row(run_id)
    assert out["canonical_ret_dd"] == 2.47
    got = _read(patched_state, run_id)
    assert got["canonical_ret_dd"] == 2.47
    assert got["canonical_net_pct"] == 22.2
    assert got["cycles_completed"] == 14
    assert got["metrics_fn_version"] == METRICS_FN_VERSION
    # provenance / identity immutable
    assert got["pair_a"] == "EURUSD"
    assert got["directive_id"] == "DIR"
    assert got["test_start"] == "2025-01-01"


def test_reenrich_sha_mismatch_refuses(patched_state, monkeypatch):
    run_id, pq = _make_run(patched_state)
    pq.write_bytes(b"DIFFERENT-bytes--substrate-changed")  # sha no longer matches
    _patch_cm(monkeypatch)
    with pytest.raises(ReenrichError, match="mismatch"):
        reenrich_cointegration_row(run_id)


def test_reenrich_missing_substrate_refuses(patched_state):
    run_id, pq = _make_run(patched_state)
    pq.unlink()  # substrate lost
    with pytest.raises(ReenrichError, match="missing"):
        reenrich_cointegration_row(run_id)


def test_reenrich_unknown_run_refuses(patched_state):
    _make_run(patched_state)  # ensures the table exists
    with pytest.raises(ReenrichError, match="no current"):
        reenrich_cointegration_row("DOES_NOT_EXIST")


def test_retention_guard_recovers_basket_id_from_folder(patched_state):
    run_id, _ = _make_run(patched_state)
    from tools.state_lifecycle.lineage_pruner import _cointegration_keep_info
    info = _cointegration_keep_info()
    assert run_id in info
    assert info[run_id] == ("DIR", "H2")  # basket_id recovered from "<DIR>_H2"
