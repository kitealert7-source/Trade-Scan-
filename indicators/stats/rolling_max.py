import pandas as pd

def rolling_max(series: pd.Series, window: int) -> pd.Series:
    """
    Calculate rolling maximum over a specified window.
    
    Args:
        series (pd.Series): Input data series
        window (int): Size of the moving window
        
    Returns:
        pd.Series: Rolling maximum values
    """
    return series.rolling(window=window, min_periods=1).max()
