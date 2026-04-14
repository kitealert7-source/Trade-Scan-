"""
Swing Pivots — True Symmetric Pivot Detection

Detects confirmed swing-pivot highs and lows using a symmetric left/right
window of k bars. A pivot is only confirmed k bars after the fact (no
repainting beyond confirmation delay, no forward-looking leakage at the
pivot bar itself — the flag only materializes once the full right-side
window has printed).

Definition (k = 3, fixed):
    pivot_high[i] = high[i] >  max(high[i-k : i])      # strictly greater than k bars to the left
                    AND high[i] >= max(high[i+1 : i+k+1])  # at least as high as k bars to the right
    pivot_low[i]  = low[i]  <  min(low[i-k : i])
                    AND low[i]  <= min(low[i+1 : i+k+1])

The strict-left / non-strict-right asymmetry resolves flat ties to the
earlier pivot (deterministic, no duplicate pivots within the window).

Required input columns:
    ['high', 'low']

Output columns:
    pivot_high_flag   — int {0,1}: 1 at a confirmed swing-high bar
    pivot_low_flag    — int {0,1}: 1 at a confirmed swing-low bar
    pivot_high_price  — float: the pivot high's price at that bar (NaN elsewhere)
    pivot_low_price   — float: the pivot low's price at that bar (NaN elsewhere)
"""

import numpy as np
import pandas as pd

_K = 3  # fixed symmetric window (bars to left and right)


def compute_swing_pivots(df: pd.DataFrame) -> pd.DataFrame:
    """Compute confirmed symmetric swing pivots with k=3."""
    n = len(df)
    high = df['high'].to_numpy(dtype=float)
    low  = df['low'].to_numpy(dtype=float)

    pivot_high_flag = np.zeros(n, dtype=int)
    pivot_low_flag  = np.zeros(n, dtype=int)
    pivot_high_price = np.full(n, np.nan, dtype=float)
    pivot_low_price  = np.full(n, np.nan, dtype=float)

    # Valid range: need k bars on both sides
    for i in range(_K, n - _K):
        left_hi  = high[i - _K : i].max()
        right_hi = high[i + 1 : i + _K + 1].max()
        if high[i] > left_hi and high[i] >= right_hi:
            pivot_high_flag[i] = 1
            pivot_high_price[i] = high[i]

        left_lo  = low[i - _K : i].min()
        right_lo = low[i + 1 : i + _K + 1].min()
        if low[i] < left_lo and low[i] <= right_lo:
            pivot_low_flag[i] = 1
            pivot_low_price[i] = low[i]

    df['pivot_high_flag']  = pivot_high_flag
    df['pivot_low_flag']   = pivot_low_flag
    df['pivot_high_price'] = pivot_high_price
    df['pivot_low_price']  = pivot_low_price
    return df


# Public alias — matches module-tail convention used by the strategy
# provisioner (from indicators.structure.swing_pivots import swing_pivots).
swing_pivots = compute_swing_pivots
