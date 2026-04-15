"""
Unit tests for baseline_freshness_gate.py — filesystem-isolated via monkeypatch.

Covers:
  - Fresh single-symbol baseline → OK
  - Stale single-symbol baseline → BLOCKED at 14d, OK at 30d threshold
  - Multi-symbol worst-case selection
  - Missing freshness_index → FAIL (fail-fast)
  - No baseline CSVs → FAIL
  - Threshold boundary (age == threshold passes, age > threshold blocks)
  - Unknown symbol in freshness_index → FAIL
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import baseline_freshness_gate as gate  # noqa: E402


# ───────────────────────────── fixture helpers ─────────────────────────────

def _write_index(tmp_path: Path, entries: dict) -> Path:
    idx = tmp_path / "freshness_index.json"
    idx.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return idx


def _write_baseline(backtests_dir: Path, backtest_name: str, last_date: str) -> Path:
    """Create a minimal results_tradelevel.csv with one entry row."""
    raw = backtests_dir / backtest_name / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    csv_path = raw / "results_tradelevel.csv"
    csv_path.write_text(
        f"entry_timestamp,exit_timestamp,pnl\n{last_date} 10:00:00,{last_date} 12:00:00,1.0\n",
        encoding="utf-8",
    )
    return csv_path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect the gate's paths into tmp_path and stub tf resolution."""
    backtests_dir = tmp_path / "backtests"
    backtests_dir.mkdir()
    index_path = tmp_path / "freshness_index.json"

    monkeypatch.setattr(gate, "BACKTESTS_DIR", backtests_dir)
    monkeypatch.setattr(gate, "FRESHNESS_INDEX_PATH", index_path)
    monkeypatch.setattr(gate, "_resolve_tf_from_strategy", lambda sid: "1h")

    return {"root": tmp_path, "backtests": backtests_dir, "index": index_path}


# ───────────────────────────────── tests ───────────────────────────────────

def test_fresh_single_symbol_ok(sandbox):
    _write_index(sandbox["root"], {"XAUUSD_OCTAFX_1h": {"latest_date": "2026-04-14"}})
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2026-04-10")

    r = gate.check_freshness("FOO", threshold_days=14)
    assert r.status == "OK"
    assert r.worst_age_days == 4


def test_stale_blocks_at_14_passes_at_30(sandbox):
    _write_index(sandbox["root"], {"XAUUSD_OCTAFX_1h": {"latest_date": "2026-04-14"}})
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2026-03-15")  # 30d stale

    r14 = gate.check_freshness("FOO", threshold_days=14)
    assert r14.status == "BLOCKED"
    assert r14.worst_age_days == 30

    r30 = gate.check_freshness("FOO", threshold_days=30)
    assert r30.status == "OK"  # boundary: age == threshold passes


def test_multi_symbol_worst_case(sandbox):
    _write_index(sandbox["root"], {
        "XAUUSD_OCTAFX_1h": {"latest_date": "2026-04-14"},
        "EURUSD_OCTAFX_1h": {"latest_date": "2026-04-14"},
    })
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2026-04-10")  # 4d
    _write_baseline(sandbox["backtests"], "FOO_EURUSD", "2026-03-20")  # 25d

    r = gate.check_freshness("FOO", threshold_days=14)
    assert r.status == "BLOCKED"
    assert r.worst_age_days == 25


def test_missing_freshness_index_fails_fast(sandbox):
    # Note: don't write index
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2026-04-10")

    r = gate.check_freshness("FOO", threshold_days=14)
    assert r.status == "FAIL"
    assert "freshness_index.json missing" in r.message


def test_no_baseline_csvs_fails(sandbox):
    _write_index(sandbox["root"], {"XAUUSD_OCTAFX_1h": {"latest_date": "2026-04-14"}})
    # No baselines written

    r = gate.check_freshness("FOO", threshold_days=14)
    assert r.status == "FAIL"
    assert "No baseline CSVs found" in r.message


def test_threshold_boundary_exact(sandbox):
    _write_index(sandbox["root"], {"XAUUSD_OCTAFX_1h": {"latest_date": "2026-04-15"}})
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2026-04-01")  # 14d

    r = gate.check_freshness("FOO", threshold_days=14)
    assert r.status == "OK"
    assert r.worst_age_days == 14


def test_unknown_symbol_in_index_fails(sandbox):
    _write_index(sandbox["root"], {"GBPUSD_OCTAFX_1h": {"latest_date": "2026-04-14"}})
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2026-04-10")

    r = gate.check_freshness("FOO", threshold_days=14)
    assert r.status == "FAIL"
    assert "not in freshness_index" in r.message


def test_compute_baseline_age_never_blocks(sandbox):
    """compute_baseline_age() returns OK even when stale (enforce=False)."""
    _write_index(sandbox["root"], {"XAUUSD_OCTAFX_1h": {"latest_date": "2026-04-14"}})
    _write_baseline(sandbox["backtests"], "FOO_XAUUSD", "2025-01-01")  # very stale

    r = gate.compute_baseline_age("FOO")
    assert r.status == "OK"
    assert r.worst_age_days is not None and r.worst_age_days > 300
