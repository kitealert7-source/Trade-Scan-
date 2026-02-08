"""
EMA Slope Indicator

Pure function indicator for measuring trend direction and strength.
"""
import pandas as pd


def ema_slope(close: pd.Series, period: int = 20, slope_window: int = 1) -> pd.Series:
    """
    Compute EMA and return its slope (difference over slope_window bars).
    
    Args:
        close: Close prices series
        period: EMA period (default: 20)
        slope_window: Number of bars over which to compute slope (default: 1)
        
    Returns:
        pd.Series: EMA slope values (positive = uptrend, negative = downtrend)
    """
    ema = close.ewm(span=period, adjust=False).mean()
    
    slope = ema.diff(slope_window)
    
    return slope
