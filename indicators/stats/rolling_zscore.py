
"""
Rolling Z-Score — Production-grade implementation

Features:
- Proper float dtype enforcement
- Uses population std (ddof=0)
- Safe zero-std handling
- Inf-safe
- Fully vectorized
"""

import pandas as pd
import numpy as np


def rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """
    Compute rolling z-score.

    Z = (value - rolling_mean) / rolling_std

    Args:
        series: numeric input series
        window: rolling window

    Returns:
        z-score series
    """

    # enforce numeric dtype
    series = series.astype(float)

    rolling_mean = series.rolling(
        window=window,
        min_periods=window
    ).mean()

    rolling_std = series.rolling(
        window=window,
        min_periods=window
    ).std(ddof=0)

    # safe std handling
    rolling_std = rolling_std.replace(0, np.nan)

    zscore = (series - rolling_mean) / rolling_std

    # inf safety
    zscore.replace([np.inf, -np.inf], np.nan, inplace=True)

    return zscore
