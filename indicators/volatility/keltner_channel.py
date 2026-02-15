
"""
Keltner Channel — Corrected implementation
"""

import pandas as pd
import numpy as np


def keltner_channel(df: pd.DataFrame,
                    window: int,
                    atr_mult: float):

    df = df.copy()

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # EMA mid
    kc_mid = close.ewm(span=window, adjust=False).mean()

    # True Range
    high_low = high - low
    high_close = (high - close.shift(1)).abs()
    low_close = (low - close.shift(1)).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # ATR (Wilder)
    atr = tr.ewm(alpha=1/window, adjust=False).mean()

    atr_safe = atr.replace(0, np.nan)

    kc_upper = kc_mid + atr_mult * atr_safe
    kc_lower = kc_mid - atr_mult * atr_safe

    return kc_mid, kc_upper, kc_lower
