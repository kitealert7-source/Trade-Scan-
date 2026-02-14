
import pandas as pd
import numpy as np

def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """
    Calculate rolling percentile rank (0-100) of value within window.
    
    Args:
        series: Input series
        window: Rolling window size
        
    Returns:
        pd.Series: Percentile rank (0 to 100)
    """
    # pct=True returns 0.0-1.0
    return series.rolling(window=window).rank(pct=True) * 100
