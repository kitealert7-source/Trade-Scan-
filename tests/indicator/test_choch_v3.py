"""Tests for indicators.structure.choch_v3 (structure-aware pivot CHOCH)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from indicators.structure.choch_v3 import compute_choch_v3, _K
from indicators.structure.choch_v2 import compute_choch_v2


def _make_df(highs, lows, closes):
    return pd.DataFrame({
        "high":  np.asarray(highs,  dtype=float),
        "low":   np.asarray(lows,   dtype=float),
        "close": np.asarray(closes, dtype=float),
    })


def _bullish_after_downtrend_series():
    """Downtrend structure (LL+LH) then upside break.

    Pivots constructed by hand with k=3 symmetric confirmation:
        PH1 at bar 3  (high=20)   — left ascending, right descending
        PL1 at bar 7  (low=10)
        PH2 at bar 11 (high=17)   -> LH (17<20)
        PL2 at bar 15 (low=6)     -> LL (6<10)
    Downtrend latches when PL2 confirms at bar 18.
    Then close breaks above PH2=17 (last_pivot_high_ref) to fire bullish CHOCH.
    """
    #        0   1   2   3*  4   5   6   7*  8   9   10  11* 12  13  14  15* 16  17  18  19  20  21
    highs = [12, 14, 16, 20, 18, 17, 15, 13, 14, 15, 16, 17, 16, 15, 14, 12, 14, 15, 16, 20, 20, 20]
    lows  = [11, 12, 13, 14, 13, 12, 11, 10, 11, 12, 13, 14, 13, 12, 11,  6, 11, 12, 13, 18, 18, 18]
    closes= [11, 13, 15, 19, 17, 16, 14, 11, 13, 14, 15, 16, 15, 14, 13,  7, 13, 14, 15, 19, 19, 19]
    return highs, lows, closes


def _bearish_after_uptrend_series():
    """Uptrend structure (HH+HL) then downside break.

        PL1 at bar 3  (low=6)
        PH1 at bar 7  (high=15)
        PL2 at bar 11 (low=8)     -> HL (8>6)
        PH2 at bar 15 (high=20)   -> HH (20>15)
    Uptrend latches when PH2 confirms at bar 18.
    Then close breaks below PL2=8 to fire bearish CHOCH.
    """
    #        0   1   2   3*  4   5   6   7*  8   9   10  11* 12  13  14  15* 16  17  18  19  20  21
    highs = [10, 9,  8,  7,  8,  10, 12, 15, 13, 11, 10, 9,  10, 12, 14, 20, 18, 16, 15, 12, 12, 12]
    lows  = [9,  8,  7,  6,  7,  8,  10, 13, 11, 9,  8,  8,  9,  11, 13, 18, 15, 13, 12, 7,  7,  7]
    closes= [9,  8,  7,  6,  7,  9,  11, 14, 12, 10, 9,  8,  9,  11, 13, 19, 16, 14, 13, 7,  7,  7]
    return highs, lows, closes


def test_no_signal_without_prior_structure():
    # Single pivot high at bar 5 (high=20), no prior opposing structure.
    # Even with close > 20 later, no CHOCH should fire (V3 requires structure).
    highs  = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 22, 22, 22]
    lows   = [h - 2 for h in highs]
    closes = [h - 1 for h in highs]
    df = _make_df(highs, lows, closes)
    out = compute_choch_v3(df.copy())
    events = out['choch_event_v3'].to_numpy()
    # V2 would fire at bar 11; V3 must not, because no LL+LH seen.
    assert (events == 0).all(), f"Expected no events, got {events.tolist()}"


def test_bullish_choch_only_after_ll_lh():
    highs, lows, closes = _bullish_after_downtrend_series()
    df = _make_df(highs, lows, closes)
    out = compute_choch_v3(df.copy())
    events = out['choch_event_v3'].to_numpy()
    has_dn = out['has_downtrend'].to_numpy()
    # Downtrend must be latched by bar 18 (PL2 confirmation).
    assert has_dn[18] == 1, f"has_downtrend not set by bar 18: {has_dn.tolist()}"
    # First break above last_pivot_high_ref (=17) comes at bar 19.
    assert events[19] == 1, f"Expected bullish CHOCH at 19, events={events.tolist()}"
    # Edge-triggered: subsequent bars suppressed.
    assert events[20] == 0 and events[21] == 0


def test_bearish_choch_only_after_hh_hl():
    highs, lows, closes = _bearish_after_uptrend_series()
    df = _make_df(highs, lows, closes)
    out = compute_choch_v3(df.copy())
    events = out['choch_event_v3'].to_numpy()
    has_up = out['has_uptrend'].to_numpy()
    assert has_up[18] == 1, f"has_uptrend not set by bar 18: {has_up.tolist()}"
    assert events[19] == -1, f"Expected bearish CHOCH at 19, events={events.tolist()}"
    assert events[20] == 0 and events[21] == 0


def test_edge_trigger_correctness():
    highs, lows, closes = _bullish_after_downtrend_series()
    df = _make_df(highs, lows, closes)
    out = compute_choch_v3(df.copy())
    raw = out['choch_event_v3_raw'].to_numpy()
    evt = out['choch_event_v3'].to_numpy()
    for i in range(len(raw)):
        prev_r = raw[i - 1] if i > 0 else 0
        expected = raw[i] if (raw[i] != 0 and prev_r == 0) else 0
        assert evt[i] == expected, f"bar {i}: raw={raw[i]} prev={prev_r} evt={evt[i]} expected={expected}"


def test_no_forward_leakage():
    highs, lows, closes = _bullish_after_downtrend_series()
    df1 = _make_df(highs, lows, closes)
    out1 = compute_choch_v3(df1.copy())
    # Mutate the last bar only; bars up to 19 must be invariant.
    highs2 = list(highs); highs2[-1] = 999
    closes2 = list(closes); closes2[-1] = 999
    df2 = _make_df(highs2, lows, closes2)
    out2 = compute_choch_v3(df2.copy())
    assert out1.loc[19, 'choch_event_v3'] == out2.loc[19, 'choch_event_v3'] == 1


def test_matches_v2_once_structure_is_satisfied():
    """After structure latches, V3 events should coincide with V2 events on
    bars where V2 would also fire (since V3 is a strict subset of V2)."""
    highs, lows, closes = _bullish_after_downtrend_series()
    df = _make_df(highs, lows, closes)
    v2 = compute_choch_v2(df.copy())['choch_event_v2'].to_numpy()
    v3 = compute_choch_v3(df.copy())['choch_event_v3'].to_numpy()
    # V3 is a subset of V2: every V3 event must exist in V2 (same sign).
    for i in range(len(v2)):
        if v3[i] != 0:
            assert v2[i] == v3[i], f"bar {i}: v3={v3[i]} v2={v2[i]}"
    # And on bar 19, both should be +1 (structure satisfied, pivot break).
    assert v2[19] == 1 and v3[19] == 1


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
