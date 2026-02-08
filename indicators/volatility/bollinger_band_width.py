"""
Bollinger Band Width Indicator

Pure function indicator for measuring volatility compression/expansion.
"""
import pandas as pd
import numpy as np


def bollinger_band_width(series: pd.Series, window: int, std_mult: float) -> pd.Series:
    """
    Compute Bollinger Band Width (volatility compression indicator).
    
    BB Width = (Upper - Lower) / Mid
    
    Args:
        series: Input price series (typically close)
        window: Rolling window for mean and std
        std_mult: Standard deviation multiplier for bands
        
    Returns:
        pd.Series: Bollinger Band Width values (raw ratio)
    """
    # Enforce numeric
    series = series.astype(float)
    
    # Rolling statistics
    mid = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    
    # Bands
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    
    # NaN safety: replace zero mid with NaN before division
    mid_safe = mid.replace(0, np.nan)
    
    # BB Width
    bb_width = (upper - lower) / mid_safe
    
    return bb_width
