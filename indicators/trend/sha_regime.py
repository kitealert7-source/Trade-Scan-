
"""
sha_regime.py

Smoothed Heikin Ashi regime filter (optimized numpy version)

Column Naming:
    Accepts lowercase open/high/low/close (engine standard) with
    fallback to capitalized Open/High/Low/Close for legacy compatibility.
    Raises ValueError if neither is present.
"""

import numpy as np
import pandas as pd

def sha_regime(df: pd.DataFrame, smooth: int = 3) -> pd.DataFrame:

    # -------------------------------------------------------------------------
    # GOVERNANCE: Column Naming Standardization
    # Prefer lowercase (engine convention). Fall back to capitalized.
    # -------------------------------------------------------------------------
    _lc = {"open", "high", "low", "close"}
    _uc = {"Open", "High", "Low", "Close"}

    if _lc.issubset(df.columns):
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
    elif _uc.issubset(df.columns):
        o = df["Open"].values
        h = df["High"].values
        l = df["Low"].values
        c = df["Close"].values
    else:
        present = list(df.columns)
        raise ValueError(
            f"sha_regime: All four OHLC columns required. "
            f"Expected {sorted(_lc)} (lowercase) or {sorted(_uc)} (capitalized). "
            f"Found: {present}"
        )

    n = len(df)

    ha_open = np.zeros(n)
    ha_close = (o + h + l + c) / 4.0
    ha_high = np.zeros(n)
    ha_low = np.zeros(n)

    ha_open[0] = (o[0] + c[0]) / 2.0
    ha_high[0] = h[0]
    ha_low[0] = l[0]

    # GOVERNANCE: iterative by design (O(n)), no nested loops.
    # HA open at bar i depends on prior HA values — inherently sequential.
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
