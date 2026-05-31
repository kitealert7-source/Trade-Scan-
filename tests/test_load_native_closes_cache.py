"""Regression test for the per-process LRU cache on `_load_native_closes`.

Landed 2026-05-31 to amortize BC4-style backfill data loading: workers re-load
the same (symbol, tf) full history on every (as_of, tf) task. The cache traps
the heavy work (`_load_full_history`) behind a process-local lru_cache so the
year-file CSV reads happen once per (symbol, tf) per process.

Tests in this file:
  * First call misses, second call hits, third with different key misses again.
  * `pd.read_csv` is invoked on the first call only — the heart of the
    "no disk re-read on warm calls" claim.
  * The cached path still returns correctly-windowed data when `start`/`end`
    are passed (cache holds the FULL series; slice happens on read).
  * No-slice path returns a defensive copy — mutating the result doesn't
    corrupt the cache for the next caller.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def synthetic_research_dir(tmp_path, monkeypatch):
    """Stand up a fake MASTER_DATA tree with two symbols × two TFs of CSVs.

    Each CSV holds 5 daily bars. The fixture monkey-patches `_research_dir`
    so the cache loader reads from `tmp_path` instead of the real
    Anti_Gravity_DATA_ROOT — keeps the test hermetic and Linux-runnable.
    """
    root = tmp_path / "MASTER_DATA"
    csv_count = {"n": 0}

    real_read_csv = pd.read_csv

    def _counting_read_csv(*a, **kw):
        csv_count["n"] += 1
        return real_read_csv(*a, **kw)

    def _make(sym: str, tf: str, year: int, base: float):
        d = root / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{sym}_OCTAFX_{tf}_{year}_RESEARCH.csv"
        df = pd.DataFrame({
            "time": pd.date_range(f"{year}-01-01", periods=5, freq="D"),
            "open": [base] * 5,
            "high": [base + 0.1] * 5,
            "low": [base - 0.1] * 5,
            "close": [base + i * 0.01 for i in range(5)],
        })
        df.to_csv(path, index=False)

    _make("EURUSD", "1d", 2024, 1.05)
    _make("EURUSD", "1d", 2025, 1.10)
    _make("GBPUSD", "1d", 2024, 1.25)

    from tools.factors import fx_correlation_matrix as fcm
    monkeypatch.setattr(fcm, "_research_dir",
                         lambda sym: root / f"{sym}_OCTAFX_MASTER" / "RESEARCH")
    monkeypatch.setattr(pd, "read_csv", _counting_read_csv)
    fcm._load_full_history.cache_clear()

    yield {"root": root, "csv_count": csv_count, "fcm": fcm}

    fcm._load_full_history.cache_clear()


def test_first_call_misses_second_call_hits_same_key(synthetic_research_dir):
    fcm = synthetic_research_dir["fcm"]
    csv_count = synthetic_research_dir["csv_count"]

    fcm._load_native_closes("EURUSD", "1d", None, None)
    info1 = fcm._load_full_history.cache_info()
    assert info1.misses == 1
    assert info1.hits == 0
    assert csv_count["n"] == 2  # EURUSD 1d has 2 year-files

    fcm._load_native_closes("EURUSD", "1d", None, None)
    info2 = fcm._load_full_history.cache_info()
    assert info2.misses == 1
    assert info2.hits == 1
    assert csv_count["n"] == 2  # no new reads — the cache hit


def test_different_symbol_or_tf_misses(synthetic_research_dir):
    fcm = synthetic_research_dir["fcm"]
    csv_count = synthetic_research_dir["csv_count"]

    fcm._load_native_closes("EURUSD", "1d", None, None)
    fcm._load_native_closes("GBPUSD", "1d", None, None)

    info = fcm._load_full_history.cache_info()
    assert info.misses == 2
    assert info.hits == 0
    assert csv_count["n"] == 3  # EURUSD: 2 reads, GBPUSD: 1 read


def test_start_end_slicing_returns_correct_window(synthetic_research_dir):
    fcm = synthetic_research_dir["fcm"]

    full = fcm._load_native_closes("EURUSD", "1d", None, None)
    assert len(full) == 10  # 5 bars × 2 years

    sliced = fcm._load_native_closes(
        "EURUSD", "1d",
        pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-03"),
    )
    assert len(sliced) == 3
    assert sliced.index.min() == pd.Timestamp("2025-01-01")
    assert sliced.index.max() == pd.Timestamp("2025-01-03")

    info = fcm._load_full_history.cache_info()
    assert info.misses == 1  # both calls used the same cached full series
    assert info.hits == 1


def test_no_slice_path_returns_defensive_copy(synthetic_research_dir):
    """Mutating the returned Series on the no-slice path must NOT corrupt the
    cache. Requirement #4: 'if uncertain, return a defensive copy.'"""
    fcm = synthetic_research_dir["fcm"]

    s1 = fcm._load_native_closes("EURUSD", "1d", None, None)
    original_first = float(s1.iloc[0])
    s1.iloc[0] = -999.0  # mutate the returned Series

    s2 = fcm._load_native_closes("EURUSD", "1d", None, None)
    assert float(s2.iloc[0]) == original_first, (
        "Cache was corrupted by caller mutation — defensive copy missing."
    )


def test_repeated_loads_under_typical_bc4_pattern_keep_csv_reads_flat(
    synthetic_research_dir,
):
    """Mimic the BC4 worker pattern: same (symbol, tf) requested with many
    different end-date cutoffs. The cache must hold disk reads at the
    one-time cost while serving many windows."""
    fcm = synthetic_research_dir["fcm"]
    csv_count = synthetic_research_dir["csv_count"]

    cutoffs = [pd.Timestamp(f"2024-01-{d:02d}") for d in range(1, 6)] + \
              [pd.Timestamp(f"2025-01-{d:02d}") for d in range(1, 6)]
    for as_of in cutoffs:
        fcm._load_native_closes("EURUSD", "1d", None, as_of)

    info = fcm._load_full_history.cache_info()
    assert info.misses == 1
    assert info.hits == 9
    assert csv_count["n"] == 2, (
        f"Expected 2 CSV reads (one per year-file, on first call only); "
        f"got {csv_count['n']}. Cache is not amortizing disk reads."
    )
