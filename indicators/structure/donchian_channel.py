"""
Donchian Channel Indicator

Pure function indicator for computing structure context (high/low channel).
"""
import pandas as pd


def donchian_channel(series: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    """
    Compute Donchian Channel.
    
    Args:
        series: Input price series (typically close, or high/low separately)
        window: Rolling window for max/min
        
    Returns:
        tuple of (dc_mid, dc_width):
            dc_mid   : (high + low) / 2
            dc_width : high - low
    """
    # Enforce numeric
    series = series.astype(float)
    
    # Rolling max and min
    high = series.rolling(window).max()
    low = series.rolling(window).min()
    
    # Donchian mid and width
    dc_mid = (high + low) / 2
    dc_width = high - low
    
    return dc_mid, dc_width
