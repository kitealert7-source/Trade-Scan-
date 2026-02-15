
"""
Stochastic %K — Production-grade implementation

Features:
- Safe denominator handling
- Prevents NaN propagation
- Fully vectorized
- Continuous output
"""

import pandas as pd
import numpy as np


def stochastic_k(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    smooth_period: int = 3
) -> pd.Series:
    """
    Calculate smoothed stochastic %K.

    Args:
        high: high price series
        low: low price series
        close: close price series
        k_period: lookback period
        smooth_period: smoothing window

    Returns:
        smoothed %K series (0–100)
    """

    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)

    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()

    denominator = highest_high - lowest_low

    # Safe division
    raw_k = 100.0 * (close - lowest_low) / denominator.replace(0, np.nan)

    # Forward fill to maintain continuity
    raw_k = raw_k.fillna(method="ffill")

    # Smooth
    smoothed_k = raw_k.rolling(
        window=smooth_period,
        min_periods=smooth_period
    ).mean()

    return smoothed_k
