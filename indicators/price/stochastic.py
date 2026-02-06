"""
Stochastic %K Implementation
Pure math implementation using pandas.
"""
import pandas as pd
import numpy as np

def stochastic_k(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, smooth_period: int = 3) -> pd.Series:
    """
    Calculate Stochastic %K.
    
    Formula:
        %K = 100 * (close - lowest_low) / (highest_high - lowest_low)
        Smoothed by SMA of length smooth_period.
        
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of close prices
        k_period: Lookback period for Min/Max
        smooth_period: Smoothing period for %K
        
    Returns:
        pandas Series containing Smoothed %K values (0-100)
    """
    # Calculate Rolling Min/Max
    # min_periods should be k_period to ensure we have enough data? 
    # Standard usually allows partial? Let's use k_period for strictness to avoid noise at start.
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    
    # Calculate Raw %K
    # Handle potential division by zero if high == low (flat market)
    denominator = highest_high - lowest_low
    
    # Avoid division by zero
    # If denominator is 0, it means High == Low. The value of K depends on position.
    # Usually we can set to 50 or 0 or keep NaN. Let's assume 50 (middle) or prev value.
    # Standard approach: replace 0 with NaN then fill, or handle explicitly.
    # Using numpy to handle it safely.
    
    # Safe division
    numerator = 100 * (close - lowest_low)
    
    # If denominator is 0, result is undefined (NaN) or handle specific case.
    # Usually returning 50 is neutral, or NaN. Let's stick to NaN for safety.
    raw_k = numerator / denominator
    
    # Apply Smoothing (SMA)
    smoothed_k = raw_k.rolling(window=smooth_period, min_periods=smooth_period).mean()
    
    return smoothed_k
