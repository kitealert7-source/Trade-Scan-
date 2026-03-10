"""
Relative Strength Index (RSI) Implementation
Pure math implementation using pandas.
"""
import pandas as pd
import numpy as np

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI) using Wilder's Smoothing.
    
    Args:
        series: pandas Series of prices
        period: Lookback period (default 14)
        
    Returns:
        pandas Series containing RSI values (0-100)
    """
    # Calculate price changes
    delta = series.diff()
    
    # Separate gains and losses
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    # Calculate initial average gain/loss (SMA)
    # Wilder's smoothing starts with a simple average for the first period
    # However, standard pandas ewm with adjust=False and alpha=1/n mimics Wilder's exactly 
    # if strictly applied.
    
    # Using ewm(alpha=1/period, adjust=False) is the standard Wilder's implementation in pandas context.
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    
    # Calculate RS
    rs = avg_gain / avg_loss
    
    # Calculate RSI
    rsi_series = 100 - (100 / (1 + rs))
    
    # Handle divide-by-zero only (avg_loss == 0 -> RSI = 100)
    rsi_series = rsi_series.replace([np.inf], 100.0)
    
    # Preserve warmup NaNs
    rsi_series.iloc[:period] = np.nan
    
    return rsi_series
