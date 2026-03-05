"""
Hurst Regime Detector — Vectorized implementation

Purpose
-------
Detect persistence regimes using Hurst exponent.

Interpretation
--------------
H < 0.45  → mean-reverting
0.45–0.55 → random / neutral
H > 0.55  → persistent trend

Outputs
-------
hurst   : estimated Hurst exponent
regime  : -1 (mean-reversion), 0 (neutral), 1 (persistent trend)
"""

import pandas as pd
import numpy as np


def hurst_regime(series: pd.Series,
                 window: int = 200,
                 max_lag: int = 20) -> pd.DataFrame:

    # Hurst should be estimated on log-price levels; using returns collapses
    # values near zero and makes thresholds like 0.55 non-operational.
    series = pd.to_numeric(series, errors="coerce").astype(float)
    log_price = np.log(series.where(series > 0))

    lags = np.arange(2, max_lag)

    def hurst_calc(x):

        if np.isnan(x).any():
            return np.nan

        tau = []

        for lag in lags:
            diff = x[lag:] - x[:-lag]
            tau.append(np.std(diff))

        tau = np.array(tau)

        if np.any(tau <= 0):
            return np.nan

        poly = np.polyfit(np.log(lags), np.log(tau), 1)

        return poly[0]


    hurst = log_price.rolling(
        window=window,
        min_periods=window
    ).apply(hurst_calc, raw=True)

    regime = np.where(
        hurst > 0.55, 1,
        np.where(hurst < 0.45, -1, 0)
    )

    regime[:window] = 0

    return pd.DataFrame({
        "hurst": hurst.values,
        "regime": regime
    }, index=series.index)
