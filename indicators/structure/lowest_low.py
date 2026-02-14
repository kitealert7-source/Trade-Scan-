
import pandas as pd

def lowest_low(series: pd.Series, window: int, shift: int = 0) -> pd.Series:
    """
    Calculate Lowest Low over a rolling window.
    
    Args:
        series: Input series (typically Low prices)
        window: Rolling window size
        shift: Number of bars to shift the result (default 0)
        
    Returns:
        pd.Series: Lowest Low values
    """
    return series.rolling(window=window).min().shift(shift)
