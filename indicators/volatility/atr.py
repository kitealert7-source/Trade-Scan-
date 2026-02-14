import pandas as pd
import numpy as np

def atr(df: pd.DataFrame, window: int) -> pd.Series:
    """
    Calculate Average True Range (ATR) using Wilder's Smoothing (RMA).

    Args:
        df: DataFrame containing 'high', 'low', 'close' columns
        window: Lookback period

    Returns:
        pd.Series: ATR values
    """
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # Wilder's RMA
    atr = tr.ewm(alpha=1/window, adjust=False).mean()

    return atr
