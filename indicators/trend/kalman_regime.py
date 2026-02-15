
"""
Kalman Regime — dtype-safe implementation
"""

import pandas as pd
import numpy as np


def kalman_regime(df, price_col="Close",
                  process_var=1e-5,
                  measurement_var=1e-2):

    prices = df[price_col].astype(float).values

    n = len(prices)

    trend = np.zeros(n)
    regime = np.zeros(n, dtype=int)

    x = prices[0]
    P = 1.0

    trend[0] = x

    for i in range(1, n):

        P_pred = P + process_var
        K = P_pred / (P_pred + measurement_var)

        x = x + K * (prices[i] - x)
        P = (1 - K) * P_pred

        trend[i] = x

        regime[i] = 1 if trend[i] > trend[i-1] else -1

    return pd.DataFrame({
        "trend": trend,
        "regime": regime
    }, index=df.index)
