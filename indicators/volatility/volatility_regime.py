"""
Volatility Regime — Vectorized implementation (Three-Bucket Structure)

Regime Encoding:
    -1 → Low Volatility    (Percentile <= 0.33)
     0 → Medium Volatility (0.33 < Percentile < 0.66)
     1 → High Volatility   (Percentile >= 0.66)

Designed for cross-strategy reuse.
Rolling-based. No lookahead.
"""

import pandas as pd
import numpy as np


def volatility_regime(
    atr_series: pd.Series,
    window: int = 100,
    low_thresh: float = 0.33,
    high_thresh: float = 0.66
):

    atr_series = atr_series.astype(float)

    def percentile_last(x):
        # Percentile rank of latest ATR within rolling window
        return np.sum(x <= x[-1]) / len(x)

    percentile = atr_series.rolling(
        window=window,
        min_periods=window
    ).apply(percentile_last, raw=True)

    # Default to Medium regime (0)
    regime = np.zeros(len(atr_series), dtype=int)

    # Assign High regime
    regime[percentile >= high_thresh] = 1

    # Assign Low regime
    regime[percentile <= low_thresh] = -1

    # Medium remains 0

    return pd.DataFrame({
        "atr": atr_series.values,
        "percentile": percentile.values,
        "regime": regime
    }, index=atr_series.index)
