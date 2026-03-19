"""
Bollinger Bands Indicator

Pure function indicator returning upper, lower, and midline bands.
"""
import pandas as pd
import numpy as np


def bollinger_bands(series: pd.Series, window: int, std_mult: float) -> pd.DataFrame:
    """
    Compute Bollinger Bands (upper, lower, midline).

    Args:
        series: Input price series (typically close)
        window: Rolling window for mean and std
        std_mult: Standard deviation multiplier for bands

    Returns:
        pd.DataFrame with columns: bb_upper, bb_lower, bb_midline
    """
    series = series.astype(float)

    mid = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)

    upper = mid + std_mult * std
    lower = mid - std_mult * std

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_lower": lower,
        "bb_midline": mid,
    }, index=series.index)
