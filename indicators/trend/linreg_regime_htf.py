
"""
Linear Regression Regime HTF (Higher Timeframe Approximation)
--------------------------------------------------------------
Uses long-window linear regression slope to approximate
higher timeframe structural bias without resampling.

Default window: 200 periods

Outputs:
- trend  : rolling mean (for structural context)
- slope  : linear regression slope
- regime : {-1, 0, 1}
           1  = Uptrend
           -1 = Downtrend
           0  = Not enough data (warmup zone)
"""

import pandas as pd
import numpy as np


def linreg_regime_htf(series: pd.Series,
                      window: int = 200) -> pd.DataFrame:

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

    regime = np.zeros(len(series), dtype=int)
    regime[slope > 0] = 1
    regime[slope < 0] = -1

    # Warmup zone
    regime[:window] = 0

    return pd.DataFrame({
        "trend": trend.values,
        "slope": slope.values,
        "regime": regime
    }, index=series.index)
