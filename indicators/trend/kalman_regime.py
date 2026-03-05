
"""
Kalman Regime — dtype-safe implementation

Column Naming:
    Accepts lowercase 'close' (engine standard) with fallback to 'Close'.
    Raises ValueError if neither is present.
"""

import pandas as pd
import numpy as np


def kalman_regime(df, price_col=None,
                  process_var=1e-5,
                  measurement_var=1e-2):

    # -------------------------------------------------------------------------
    # GOVERNANCE: Column Naming Standardization
    # Prefer lowercase 'close' (engine convention).
    # Fall back to capitalized 'Close' for legacy compatibility.
    # -------------------------------------------------------------------------
    if price_col is None:
        if "close" in df.columns:
            price_col = "close"
        elif "Close" in df.columns:
            price_col = "Close"
        else:
            raise ValueError(
                "kalman_regime: DataFrame must contain 'close' (preferred) "
                "or 'Close' column. Neither found."
            )

    prices = df[price_col].astype(float).values

    n = len(prices)

    trend = np.zeros(n)
    # GOVERNANCE: iterative by design (O(n)), no nested loops.
    # Kalman filter is inherently sequential — cannot be vectorized.
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
