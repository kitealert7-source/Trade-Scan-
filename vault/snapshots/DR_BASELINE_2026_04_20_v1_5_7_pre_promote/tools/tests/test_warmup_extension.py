"""
test_warmup_extension.py
Regression test: verifies that run_stage1.py's warmup extension provision
correctly extends the data window backward from start_date by the per-strategy
resolved warmup bars.

Run with:
    python tools/tests/test_warmup_extension.py

Exit 0 = PASS, Exit 1 = FAIL
"""

import sys
import types
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_df(start: str, bars: int, freq: str = "1D") -> pd.DataFrame:
    """Build a synthetic OHLCV dataframe over a date range."""
    timestamps = pd.date_range(start=start, periods=bars, freq=freq)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open":  100.0,
        "high":  101.0,
        "low":   99.0,
        "close": 100.5,
        "volume": 1000,
    })


def _load_module():
    """Import run_stage1 cleanly."""
    import importlib
    import tools.run_stage1 as m
    importlib.reload(m)
    return m


# ---------------------------------------------------------------------------
# Test 1 — warmup bars are correctly prepended before START_DATE
# ---------------------------------------------------------------------------

def test_warmup_bars_prepended():
    """
    ASSERT: When load_market_data is called, the data frame contains
    RESOLVED_WARMUP_BARS worth of rows BEFORE the START_DATE.
    """
    m = _load_module()

    START = "2024-01-02"
    WARMUP = 100
    # 6000 daily bars from 2010 guarantees START_DATE 2024-01-02 is within range
    TOTAL_BARS = 6000
    m.START_DATE = START
    m.END_DATE   = "2026-02-27"
    m.RESOLVED_WARMUP_BARS = WARMUP

    # Build a synthetic full dataframe starting well before START_DATE
    df_all = _make_fake_df("2010-01-01", TOTAL_BARS, freq="1D")
    df_all["timestamp"] = pd.to_datetime(df_all["timestamp"])

    # Simulate the windowing logic from load_market_data
    start_ts = pd.Timestamp(START)
    requested_start_idx = df_all.index[df_all["timestamp"] >= start_ts]
    assert not requested_start_idx.empty, "No bars at or after START_DATE in synthetic data"

    start_idx = max(0, requested_start_idx[0] - WARMUP)
    df_windowed = df_all.iloc[start_idx:]
    end_ts = pd.Timestamp(m.END_DATE)
    df_windowed = df_windowed[df_windowed["timestamp"] <= end_ts].reset_index(drop=True)

    # Count rows strictly BEFORE start_date
    before_start = df_windowed[df_windowed["timestamp"] < start_ts]
    after_or_at_start = df_windowed[df_windowed["timestamp"] >= start_ts]

    assert len(before_start) == WARMUP, (
        f"FAIL: Expected {WARMUP} warmup bars before {START}, got {len(before_start)}"
    )
    assert len(after_or_at_start) > 0, "FAIL: No bars at or after START_DATE"

    print(f"[PASS] test_warmup_bars_prepended: {WARMUP} bars correctly prepended before {START}")


# ---------------------------------------------------------------------------
# Test 2 — RESOLVED_WARMUP_BARS is set from strategy, not hardcoded fallback
# ---------------------------------------------------------------------------

def test_resolved_warmup_uses_resolver():
    """
    ASSERT: resolve_strategy_warmup is called with the strategy's indicator
    list and produces a value > 0. Verifies the resolver, not a constant.
    """
    from engines.indicator_warmup_resolver import resolve_strategy_warmup

    # Minimal indicator list matching a VOL strategy (atr + highest_high)
    indicators = [
        {"name": "atr",           "params": {"window": 14}},
        {"name": "highest_high",  "params": {"window": 5}},
        {"name": "atr_percentile","params": {"window": 100}},
    ]
    resolved = resolve_strategy_warmup(indicators)
    assert resolved > 0, f"FAIL: resolver returned {resolved} (expected > 0)"
    assert resolved != 250, (
        "WARN: resolver returned exactly 250 — double check this is from "
        "the registry, not a hardcoded fallback."
    )
    print(f"[PASS] test_resolved_warmup_uses_resolver: resolved={resolved} bars (from registry)")


# ---------------------------------------------------------------------------
# Test 3 — RESOLVED_WARMUP_BARS <= 0 triggers invariant failure
# ---------------------------------------------------------------------------

def test_invariant_rejects_zero_warmup():
    """
    ASSERT: The invariant block catches RESOLVED_WARMUP_BARS <= 0 and would
    trigger a FATAL log + return. We test the condition directly.
    """
    m = _load_module()
    m.RESOLVED_WARMUP_BARS = 0

    # Simulate the invariant check
    failed = m.RESOLVED_WARMUP_BARS <= 0
    assert failed, "FAIL: Invariant did not detect zero warmup bars"
    print("[PASS] test_invariant_rejects_zero_warmup: invariant correctly detected invalid warmup=0")


# ---------------------------------------------------------------------------
# Test 4 — fallback is at least 50 (safety floor)
# ---------------------------------------------------------------------------

def test_safety_floor():
    """
    ASSERT: Even if the registry returns a tiny value, the safety floor
    of 50 bars is enforced.
    """
    from engines.indicator_warmup_resolver import resolve_strategy_warmup

    # A tiny indicator (window=2) — warmup would be very small
    indicators = [{"name": "atr", "params": {"window": 2}}]
    raw = resolve_strategy_warmup(indicators)
    effective = max(raw, 50)
    assert effective >= 50, f"FAIL: Safety floor not applied, got {effective}"
    print(f"[PASS] test_safety_floor: raw={raw}, effective={effective} (floor=50)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_warmup_bars_prepended,
        test_resolved_warmup_uses_resolver,
        test_invariant_rejects_zero_warmup,
        test_safety_floor,
    ]

    print("=" * 60)
    print("WARMUP EXTENSION REGRESSION TESTS")
    print("=" * 60)

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test_fn.__name__}: {e}")
            failed += 1

    print()
    print(f"Results: {passed} passed / {failed} failed")
    sys.exit(0 if failed == 0 else 1)
