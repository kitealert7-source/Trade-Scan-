"""Tests for indicators.structure.swing_pivots (k=3 symmetric pivots)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Allow import from project root when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from indicators.structure.swing_pivots import compute_swing_pivots, _K


def _make_df(highs, lows=None):
    """Build a minimal OHLC DataFrame; lows default to highs - 1."""
    highs = np.asarray(highs, dtype=float)
    if lows is None:
        lows = highs - 1.0
    return pd.DataFrame({"high": highs, "low": np.asarray(lows, dtype=float)})


def test_single_clear_pivot_high():
    # Bar index 5 is a clear pivot high (k=3 symmetric).
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
    df = _make_df(highs)
    out = compute_swing_pivots(df.copy())
    idx = np.where(out['pivot_high_flag'].to_numpy() == 1)[0]
    assert list(idx) == [5], f"Expected pivot at 5, got {list(idx)}"
    assert out.loc[5, 'pivot_high_price'] == 20.0


def test_single_clear_pivot_low():
    lows  = [20, 19, 18, 17, 16, 10, 16, 17, 18, 19, 20]
    highs = [h + 1 for h in lows]
    df = _make_df(highs, lows)
    out = compute_swing_pivots(df.copy())
    idx = np.where(out['pivot_low_flag'].to_numpy() == 1)[0]
    assert list(idx) == [5], f"Expected pivot_low at 5, got {list(idx)}"
    assert out.loc[5, 'pivot_low_price'] == 10.0


def test_no_pivot_in_confirmation_zones():
    # First k and last k bars cannot be confirmed — never flagged.
    highs = list(range(1, 15))
    df = _make_df(highs)
    out = compute_swing_pivots(df.copy())
    flags = out['pivot_high_flag'].to_numpy()
    assert flags[:_K].sum() == 0
    assert flags[-_K:].sum() == 0


def test_no_duplicate_pivots_within_window():
    # Two equal local maxima within k bars must not both fire.
    # With strict-left/non-strict-right asymmetry, only the EARLIER fires.
    highs = [1, 2, 3, 10, 5, 10, 5, 3, 2, 1]
    df = _make_df(highs)
    out = compute_swing_pivots(df.copy())
    idx = np.where(out['pivot_high_flag'].to_numpy() == 1)[0]
    # The first 10 at index 3 should fire; the second 10 at index 5 should not
    # because left-side max (over 3 bars) is 10, not strictly less than current.
    assert 3 in idx
    assert 5 not in idx


def test_no_forward_leakage():
    # Mutating bars to the right of a confirmed pivot (outside its
    # confirmation window) must NOT retroactively change that pivot flag.
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 10, 10, 10]
    df1 = _make_df(highs)
    out1 = compute_swing_pivots(df1.copy())

    highs2 = list(highs)
    highs2[-1] = 999  # far-future spike
    df2 = _make_df(highs2)
    out2 = compute_swing_pivots(df2.copy())

    # The pivot at index 5 is confirmed at bar 5+k=8. Index 13 is far beyond.
    # Its flag must be identical in both runs.
    assert out1.loc[5, 'pivot_high_flag'] == out2.loc[5, 'pivot_high_flag'] == 1
    assert out1.loc[5, 'pivot_high_price'] == out2.loc[5, 'pivot_high_price']


def test_no_rolling_dependency():
    # Sanity: swing_pivots does not import highest_high/lowest_low.
    import indicators.structure.swing_pivots as sp
    src = Path(sp.__file__).read_text(encoding="utf-8")
    assert "highest_high" not in src
    assert "lowest_low" not in src
    assert ".rolling(" not in src


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
