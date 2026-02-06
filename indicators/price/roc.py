"""
Rate of Change (ROC) Implementation
Pure math implementation using pandas.
"""
import pandas as pd

def roc(series: pd.Series, period: int = 5) -> pd.Series:
    """
    Calculate Rate of Change (ROC).
    
    Formula:
        ROC = (price / price.shift(period) - 1) * 100
        
    Args:
        series: pandas Series of prices
        period: Shift period (default 5)
        
    Returns:
        pandas Series containing ROC values (percentage)
    """
    # Calculate Shifted Price
    shifted_price = series.shift(period)
    
    # Calculate ROC
    # (Current / Past - 1) * 100
    # Equivalent to pct_change() * 100
    
    roc_series = (series / shifted_price - 1) * 100
    
    return roc_series
