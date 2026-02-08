"""
Normalized Average True Range (ATR / Close)

Pure function indicator for measuring relative volatility.
"""
import pandas as pd
from .atr import atr as compute_atr


def atr_normalized(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute Normalized ATR (ATR / Close).
    
    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        period: Lookback period for smoothing (default: 14)
        
    Returns:
        pd.Series: Normalized ATR values (as ratio, e.g., 0.02 = 2%)
    """
    atr_values = compute_atr(high, low, close, period)
    
    # NaN safety: replace zero close with NA to avoid inf
    close_safe = close.replace(0, pd.NA)
    
    normalized = atr_values / close_safe
    
    return normalized
