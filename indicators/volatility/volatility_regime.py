
"""
Volatility Regime — Vectorized implementation
"""

import pandas as pd
import numpy as np


def volatility_regime(atr_series: pd.Series,
                      window: int = 100,
                      low_thresh: float = 0.3,
                      high_thresh: float = 0.7):

    atr_series = atr_series.astype(float)

    def percentile_last(x):
        return np.sum(x <= x[-1]) / len(x)

    percentile = atr_series.rolling(
        window=window,
        min_periods=window
    ).apply(percentile_last, raw=True)

    regime = np.zeros(len(atr_series), dtype=int)

    regime[percentile >= high_thresh] = 1
    regime[percentile <= low_thresh] = -1

    return pd.DataFrame({
        "atr": atr_series.values,
        "percentile": percentile.values,
        "regime": regime
    }, index=atr_series.index)
