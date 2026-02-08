"""
Average Directional Index (ADX)

Pure function indicator for measuring trend strength (not direction).
"""
import pandas as pd
import numpy as np


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute ADX (Average Directional Index) for trend strength.
    
    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        period: Lookback period (default: 14)
        
    Returns:
        pd.Series: ADX values (0-100 scale, higher = stronger trend)
    """
    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)
    
    # Smoothed values
    atr = true_range.ewm(span=period, adjust=False).mean()
    
    # NaN safety: replace zero ATR with nan to avoid inf
    atr_safe = atr.replace(0, np.nan)
    
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr_safe)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr_safe)
    
    # ADX
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx_series = dx.ewm(span=period, adjust=False).mean()
    
    return adx_series
