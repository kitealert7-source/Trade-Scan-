
"""
Linear Regression Regime — Vectorized implementation
"""

import pandas as pd
import numpy as np


def linreg_regime(series: pd.Series,
                  window: int = 50) -> pd.DataFrame:

    series = series.astype(float)

    x = np.arange(window)
    x_mean = x.mean()

    denom = ((x - x_mean) ** 2).sum()

    def slope_func(y):
        y_mean = y.mean()
        return ((x - x_mean) * (y - y_mean)).sum() / denom

    slope = series.rolling(
        window=window,
        min_periods=window
    ).apply(slope_func, raw=True)

    trend = series.rolling(
        window=window,
        min_periods=window
    ).mean()

    regime = np.where(slope > 0, 1, -1)
    regime[:window] = 0

    return pd.DataFrame({
        "trend": trend.values,
        "slope": slope.values,
        "regime": regime
    }, index=series.index)
