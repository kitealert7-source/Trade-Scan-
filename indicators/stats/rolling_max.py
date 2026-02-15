
"""
Rolling Maximum — Production-grade implementation

Features:
- Enforces full window for statistical consistency
- Prevents warmup distortion
- Fully vectorized
"""

import pandas as pd


def rolling_max(series: pd.Series, window: int) -> pd.Series:
    """
    Compute rolling maximum using full window.

    Args:
        series: numeric series
        window: rolling window

    Returns:
        rolling maximum series
    """

    series = series.astype(float)

    return series.rolling(
        window=window,
        min_periods=window
    ).max()
