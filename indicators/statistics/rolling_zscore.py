"""
Rolling Z-Score Indicator

Pure function indicator for measuring deviation from rolling mean.
"""
import pandas as pd


def rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """
    Compute rolling z-score of a series.
    
    Z-score = (value - rolling_mean) / rolling_std
    
    Args:
        series: Input series (price, returns, or any numeric series)
        window: Rolling window size (default: 20)
        
    Returns:
        pd.Series: Z-score values (positive = above mean, negative = below mean)
    """
    rolling_mean = series.rolling(window=window).mean()
    rolling_std = series.rolling(window=window).std()
    
    # NaN safety: replace zero std with NA to avoid inf
    rolling_std = rolling_std.replace(0, pd.NA)
    
    zscore = (series - rolling_mean) / rolling_std
    
    return zscore
