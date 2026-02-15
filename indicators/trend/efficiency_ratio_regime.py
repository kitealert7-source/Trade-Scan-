
"""
Efficiency Ratio Regime — Correct and optimized implementation
"""

import numpy as np
import pandas as pd


def efficiency_ratio_regime(series: pd.Series,
                            window: int = 20,
                            trend_threshold: float = 0.4) -> pd.DataFrame:

    series = series.astype(float)

    change = (series - series.shift(window)).abs()

    volatility = series.diff().abs().rolling(
        window=window,
        min_periods=window
    ).sum()

    er = change / volatility

    er.replace([np.inf, -np.inf], np.nan, inplace=True)

    regime = np.where(er >= trend_threshold, 1, -1)

    regime[:window] = 0

    return pd.DataFrame({
        "er": er.values,
        "regime": regime
    }, index=series.index)
