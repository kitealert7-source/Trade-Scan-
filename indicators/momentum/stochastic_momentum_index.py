"""
Stochastic Momentum Index (SMI) — Production-grade implementation

Features
--------
- Fully vectorized
- Safe denominator handling
- No NaN propagation
- Continuous output
- Optional signal line
- Research / production compatible

Reference:
William Blau – Stochastic Momentum Index
"""

import pandas as pd
import numpy as np


def stochastic_momentum_index(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    smooth1: int = 3,
    smooth2: int = 3,
    signal_period: int = 3
) -> pd.DataFrame:
    """
    Calculate the Stochastic Momentum Index (SMI).

    Parameters
    ----------
    high : pd.Series
        High price series
    low : pd.Series
        Low price series
    close : pd.Series
        Close price series
    period : int
        Lookback period for highest/lowest range
    smooth1 : int
        First EMA smoothing
    smooth2 : int
        Second EMA smoothing
    signal_period : int
        EMA period for signal line

    Returns
    -------
    pd.DataFrame
        Columns:
        - smi
        - smi_signal
        - smi_hist
    """

    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)

    # Highest / lowest window
    lowest_low = low.rolling(window=period, min_periods=period).min()
    highest_high = high.rolling(window=period, min_periods=period).max()

    midpoint = (highest_high + lowest_low) / 2.0
    half_range = (highest_high - lowest_low) / 2.0

    # Distance from midpoint
    diff = close - midpoint

    # Double smoothing (numerator)
    sm_diff = diff.ewm(span=smooth1, adjust=False).mean()
    sm_diff = sm_diff.ewm(span=smooth2, adjust=False).mean()

    # Double smoothing (denominator)
    sm_range = half_range.ewm(span=smooth1, adjust=False).mean()
    sm_range = sm_range.ewm(span=smooth2, adjust=False).mean()

    # Safe division
    smi = 100.0 * sm_diff / sm_range.replace(0, np.nan)

    # Forward fill to prevent NaN propagation
    smi = smi.fillna(method="ffill")

    # Signal line
    smi_signal = smi.ewm(span=signal_period, adjust=False).mean()

    # Histogram (momentum spread)
    smi_hist = smi - smi_signal

    return pd.DataFrame(
        {
            "smi": smi,
            "smi_signal": smi_signal,
            "smi_hist": smi_hist,
        }
    )