import pandas as pd

def ema(series: pd.Series, window: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).
    
    Args:
        series (pd.Series): Input price series
        window (int): Lookback window size
        
    Returns:
        pd.Series: EMA values
    """
    return series.ewm(span=window, adjust=False).mean()
