
import pandas as pd

def highest_high(series: pd.Series, window: int, shift: int = 0) -> pd.Series:
    """
    Calculate Highest High over a rolling window.
    
    Args:
        series: Input series (typically High prices)
        window: Rolling window size
        shift: Number of bars to shift the result (default 0)
        
    Returns:
        pd.Series: Highest High values
    """
    return series.rolling(window=window).max().shift(shift)
