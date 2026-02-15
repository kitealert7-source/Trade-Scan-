
"""
Market State — Vectorized implementation
"""

import numpy as np
import pandas as pd


def market_state(trend_slope: pd.Series,
                 volatility_percentile: pd.Series,
                 slope_thresh: float = 0.0,
                 vol_low: float = 0.3,
                 vol_high: float = 0.7):

    slope = trend_slope.astype(float)
    vol = volatility_percentile.astype(float)

    state = np.zeros(len(slope), dtype=int)

    trending_up = (slope > slope_thresh) & (vol > vol_low)
    trending_down = (slope < -slope_thresh) & (vol > vol_low)

    ranging_low = vol <= vol_low
    ranging_high = vol >= vol_high

    state[trending_up] = 1
    state[trending_down] = 2
    state[ranging_low] = 3
    state[ranging_high] = 4

    state[np.isnan(slope) | np.isnan(vol)] = 0

    return pd.DataFrame({
        "state": state
    }, index=trend_slope.index)
