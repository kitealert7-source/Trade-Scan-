"""Tests for indicators.structure.choch_v2 (pivot-based CHOCH)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from indicators.structure.choch_v2 import compute_choch_v2, _K


def _make_df(highs, lows, closes):
    return pd.DataFrame({
        "high":  np.asarray(highs,  dtype=float),
        "low":   np.asarray(lows,   dtype=float),
        "close": np.asarray(closes, dtype=float),
    })


def test_bullish_choch_fires_on_break_of_pivot_high():
    # Build a clear pivot high at bar 5 (value 20). Then push close above it.
    highs  = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 22, 22, 22]
    lows   = [h - 2 for h in highs]
    closes = [h - 1 for h in highs]
    df = _make_df(highs, lows, closes)
    out = compute_choch_v2(df.copy())
    events = out['choch_event_v2'].to_numpy()
    # Pivot at index 5 confirmed at 5+k=8; first close > 20 is at index 11.
    assert events[11] == 1, f"Expected +1 at 11, got events={events.tolist()}"
    # Subsequent consecutive breaks must be suppressed (edge-triggered).
    assert events[12] == 0
    assert events[13] == 0


def test_bearish_choch_fires_on_break_of_pivot_low():
    lows   = [20, 19, 18, 17, 16, 10, 16, 17, 18, 19, 20, 8, 8, 8]
    highs  = [l + 2 for l in lows]
    closes = [l + 1 for l in lows]
    df = _make_df(highs, lows, closes)
    out = compute_choch_v2(df.copy())
    events = out['choch_event_v2'].to_numpy()
    assert events[11] == -1, f"Expected -1 at 11, got events={events.tolist()}"
    assert events[12] == 0
    assert events[13] == 0


def test_no_event_without_confirmed_pivot():
    # Close above the first bar's high does not fire — no confirmed pivot yet.
    n = 6
    df = _make_df([10]*n, [9]*n, [11]*n)
    out = compute_choch_v2(df.copy())
    assert (out['choch_event_v2'].to_numpy() == 0).all()


def test_confirmation_delay_enforced():
    # A pivot at bar j must NOT influence bars before j+K.
    highs  = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
    lows   = [h - 2 for h in highs]
    # Force a close above 20 at bar 6 — but pivot at 5 is not yet confirmed
    # (confirms at 5+K=8). So no event should fire at 6 or 7.
    closes = [11]*5 + [21, 21, 21, 21] + [9, 9]
    df = _make_df(highs, lows, closes)
    out = compute_choch_v2(df.copy())
    events = out['choch_event_v2'].to_numpy()
    assert events[5] == 0
    assert events[6] == 0
    assert events[7] == 0
    # At bar 8 the pivot is confirmed; first break may fire there if close > 20.
    # closes[8]=21 > 20 → event should be +1 at 8.
    assert events[8] == 1


def test_no_forward_leakage():
    # Mutating far-future bars must not retroactively alter earlier events.
    highs  = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 22, 22, 22, 22, 22]
    lows   = [h - 2 for h in highs]
    closes = [h - 1 for h in highs]
    df1 = _make_df(highs, lows, closes)
    out1 = compute_choch_v2(df1.copy())

    highs2 = list(highs); highs2[-1] = 999
    closes2 = list(closes); closes2[-1] = 999
    df2 = _make_df(highs2, [h - 2 for h in highs2], closes2)
    out2 = compute_choch_v2(df2.copy())

    assert out1.loc[11, 'choch_event_v2'] == out2.loc[11, 'choch_event_v2'] == 1


def test_edge_filter_matches_raw_on_transitions():
    # The edge-triggered column should be non-zero only on 0→non-zero flips.
    highs  = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 22, 22, 22, 22, 9, 9]
    lows   = [h - 2 for h in highs]
    closes = [h - 1 for h in highs]
    df = _make_df(highs, lows, closes)
    out = compute_choch_v2(df.copy())
    raw = out['choch_event_v2_raw'].to_numpy()
    evt = out['choch_event_v2'].to_numpy()
    for i, (r, e) in enumerate(zip(raw, evt)):
        prev_r = raw[i - 1] if i > 0 else 0
        expected = r if (r != 0 and prev_r == 0) else 0
        assert e == expected, f"bar {i}: raw={r} prev={prev_r} evt={e} expected={expected}"


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed / {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)
