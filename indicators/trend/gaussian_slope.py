"""
gaussian_slope.py

Gaussian-weighted moving average + slope state for slope-flip strategies.

Contract:
  - gma: Gaussian-weighted MA over `length` bars with bell-curve weights
         (sigma controls width of the weighting curve)
  - gma_slope: first difference of gma (gma[i] - gma[i-1])
  - gma_state: +1 when slope > 0, -1 when slope < 0
               carry-forward when slope == 0 (after warmup)
               0 during warmup
  - gma_state_flip: True on bars where gma_state differs from previous bar
                    (both states must be non-zero)
  - Warmup = `length` bars
  - No aggregation. No thresholding.
"""

import numpy as np
import pandas as pd

SIGNAL_PRIMITIVE = "gma_slope_flip"
PIVOT_SOURCE = "none"


def gaussian_slope(series_or_df, length: int = 30, sigma: float = 7.0) -> pd.DataFrame:
    if length <= 0:
        raise ValueError("gaussian_slope: length must be positive")
    if sigma <= 0:
        raise ValueError("gaussian_slope: sigma must be positive")

    # --- accept Series or engine-format DataFrame ---
    if isinstance(series_or_df, pd.DataFrame):
        if "close" not in series_or_df.columns:
            raise ValueError("gaussian_slope: DataFrame input requires 'close' column")
        series = series_or_df["close"]
    else:
        series = series_or_df

    series = series.astype(float)
    n = len(series)

    # Precompute Gaussian weights, normalized to sum 1
    mid = (length - 1) / 2.0
    weights = np.exp(-((np.arange(length) - mid) ** 2) / (2.0 * sigma * sigma))
    weights = weights / weights.sum()

    # Rolling weighted average via convolution
    values = series.values
    gma = np.full(n, np.nan, dtype=float)
    if n >= length:
        kernel = weights[::-1]  # reversal harmless (symmetric); explicit for clarity
        conv = np.convolve(values, kernel, mode="valid")
        gma[length - 1:] = conv

    # Slope = first difference
    gma_slope = np.full(n, np.nan, dtype=float)
    gma_slope[1:] = gma[1:] - gma[:-1]

    # State: +1, -1, carry-forward; 0 during warmup
    warmup = length
    state = np.zeros(n, dtype=np.int8)
    prev = 0
    for i in range(n):
        if i < warmup:
            state[i] = 0
            prev = 0
            continue
        s = gma_slope[i]
        if np.isnan(s):
            state[i] = prev
            continue
        if s > 0:
            state[i] = 1
            prev = 1
        elif s < 0:
            state[i] = -1
            prev = -1
        else:
            state[i] = prev

    # Flip detection: state changed from previous bar (both non-zero)
    flip = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if state[i] != 0 and state[i - 1] != 0 and state[i] != state[i - 1]:
            flip[i] = True

    return pd.DataFrame(
        {
            "gma": gma,
            "gma_slope": gma_slope,
            "gma_state": state,
            "gma_state_flip": flip,
        },
        index=series.index,
    )


def time_requirement(params: dict, tf_minutes: int) -> int:
    length = int(params.get("length", 30))
    return length * int(tf_minutes)
