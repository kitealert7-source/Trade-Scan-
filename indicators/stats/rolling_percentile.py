
"""
Rolling Percentile Rank — Canonical Production Implementation

Features:
- Returns percentile in canonical 0–100 scale
- Statistically correct rolling percentile computation
- Deterministic and vectorized
- Enforces invariant to prevent scale corruption
"""

import pandas as pd
import numpy as np


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """
    Compute percentile rank of current value within rolling window.

    Args:
        series: numeric series
        window: rolling window

    Returns:
        percentile series (0–100 scale)
    """

    series = series.astype(float)

    def percentile_last(x):
        last = x[-1]
        count = np.sum(x <= last)
        return (count / len(x)) * 100.0

    percentile = series.rolling(
        window=window,
        min_periods=window
    ).apply(percentile_last, raw=True)

    # Enforce invariant: percentile must never exceed 100
    max_val = percentile.max(skipna=True)
    if max_val > 100.0001:
        raise RuntimeError(
            f"rolling_percentile invariant violation: max={max_val} exceeds 100"
        )

    return percentile
