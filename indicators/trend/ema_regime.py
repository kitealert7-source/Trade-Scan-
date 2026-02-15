
"""
ema_regime.py

EMA-based regime filter
"""

import pandas as pd
import numpy as np

def ema_regime(series: pd.Series, window: int = 20) -> pd.DataFrame:

    ema = series.ewm(span=window, adjust=False).mean().values

    regime = np.where(ema[1:] > ema[:-1], 1, -1)
    regime = np.insert(regime, 0, 0)

    return pd.DataFrame({
        "trend": ema,
        "regime": regime
    }, index=series.index)
