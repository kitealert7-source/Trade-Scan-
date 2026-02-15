
"""
sha_regime.py

Smoothed Heikin Ashi regime filter (optimized numpy version)
"""

import numpy as np
import pandas as pd

def sha_regime(df: pd.DataFrame, smooth: int = 3) -> pd.DataFrame:

    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values

    n = len(df)

    ha_open = np.zeros(n)
    ha_close = (o + h + l + c) / 4.0
    ha_high = np.zeros(n)
    ha_low = np.zeros(n)

    ha_open[0] = (o[0] + c[0]) / 2.0
    ha_high[0] = h[0]
    ha_low[0] = l[0]

    for i in range(1, n):

        start = max(0, i - smooth)
        avg_mid = np.mean((ha_open[start:i] + ha_close[start:i]) * 0.5)

        ha_open[i] = avg_mid
        ha_high[i] = max(h[i], ha_open[i], ha_close[i])
        ha_low[i] = min(l[i], ha_open[i], ha_close[i])

    trend = ha_close

    regime = np.where(trend[1:] > trend[:-1], 1, -1)
    regime = np.insert(regime, 0, 0)

    return pd.DataFrame({
        "trend": trend,
        "regime": regime
    }, index=df.index)
