"""
Hull Moving Average (HMA) Indicator

Pure function indicator for computing Hull Moving Average with rolling computation.
No lookahead, no full-series recomputation.
"""
import pandas as pd
import numpy as np


def _wma_apply(values: np.ndarray) -> float:
    """
    Compute Weighted Moving Average for a single window.
    Weights = 1, 2, 3, ..., n (linear increasing)
    """
    n = len(values)
    weights = np.arange(1, n + 1, dtype=float)
    return np.dot(values, weights) / weights.sum()


def _rolling_wma(series: pd.Series, window: int) -> pd.Series:
    """
    Compute rolling Weighted Moving Average.
    Each value at index t depends only on data <= t.
    """
    return series.rolling(window=window).apply(_wma_apply, raw=True)


def hull_moving_average(series: pd.Series, period: int) -> pd.Series:
    """
    Compute Hull Moving Average (HMA).
    
    HMA = WMA(2 * WMA(series, period/2) - WMA(series, period), sqrt(period))
    
    Args:
        series: Input price series (typically close)
        period: HMA period
        
    Returns:
        pd.Series: Hull Moving Average values
    """
    # Enforce numeric series
    series = series.astype(float)
    
    # Period calculations
    half_period = max(int(period / 2), 1)
    sqrt_period = max(int(np.sqrt(period)), 1)
    
    # Step 1: WMA with half period
    wma_half = _rolling_wma(series, half_period)
    
    # Step 2: WMA with full period
    wma_full = _rolling_wma(series, period)
    
    # Step 3: Difference series
    diff = 2 * wma_half - wma_full
    
    # Step 4: WMA of difference with sqrt(period)
    hma = _rolling_wma(diff, sqrt_period)
    
    return hma
