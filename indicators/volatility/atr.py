"""
Average True Range (ATR)

Pure function indicator for measuring volatility.
"""
import numpy as np
import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute Average True Range.
    
    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        period: Lookback period for smoothing (default: 14)
        
    Returns:
        pd.Series: ATR values
    """
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr_series = true_range.ewm(span=period, adjust=False).mean()
    
    return atr_series
