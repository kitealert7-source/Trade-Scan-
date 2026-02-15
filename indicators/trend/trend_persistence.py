
"""
Trend Persistence — Vectorized implementation
"""

import pandas as pd
import numpy as np


def trend_persistence(series: pd.Series,
                      window: int = 20,
                      threshold: float = 0.7) -> pd.DataFrame:

    series = series.astype(float)

    direction = np.sign(series.diff())

    up_frac = (direction > 0).rolling(
        window=window,
        min_periods=window
    ).mean()

    down_frac = (direction < 0).rolling(
        window=window,
        min_periods=window
    ).mean()

    persistence = np.maximum(up_frac, down_frac)

    regime = np.zeros(len(series), dtype=int)

    regime[up_frac >= threshold] = 1
    regime[down_frac >= threshold] = -1

    return pd.DataFrame({
        "persistence": persistence.values,
        "regime": regime
    }, index=series.index)
