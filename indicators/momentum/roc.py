
"""
Rate of Change (ROC) — Production-grade implementation

Features:
- Safe division handling
- Uses pandas native pct_change for correctness
- Fully vectorized
"""

import pandas as pd
import numpy as np


def roc(series: pd.Series, period: int = 5) -> pd.Series:
    """
    Calculate Rate of Change (ROC) as percentage.

    Args:
        series: price series
        period: lookback period

    Returns:
        ROC series (%)
    """

    series = series.astype(float)

    roc_series = series.pct_change(periods=period) * 100.0

    # handle rare edge cases safely
    roc_series.replace([np.inf, -np.inf], np.nan, inplace=True)

    return roc_series
