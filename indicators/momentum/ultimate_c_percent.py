"""
Ultimate C% — Robust Multi-Horizon Momentum Percent Rank
---------------------------------------------------------
Purpose:
    Multi-scale normalized momentum oscillator (0–100)

Designed for:
    Tactical mean reversion or momentum ignition detection.

Safe:
    - No division by zero
    - No lookahead
    - Fully vectorized
"""

import pandas as pd
import numpy as np


def ultimate_c_percent(
    df: pd.DataFrame,
    roc_period: int = 1,
    lookback: int = 5,
    factor: int = 2,
    smooth: int = 3,
    overbought: float = 75,
    oversold: float = 25,
) -> pd.DataFrame:

    if "close" not in df.columns:
        raise ValueError("DataFrame must contain 'close' column")

    close = df["close"].astype(float)

    # --- 1. Rate of Change ---
    roc = close.pct_change(periods=roc_period) * 100

    # --- 2. Percent Rank Normalization ---
    def percent_rank(series, window):
        rolling_max = series.rolling(window=window, min_periods=window).max()
        rolling_min = series.rolling(window=window, min_periods=window).min()

        denom = rolling_max - rolling_min
        denom = denom.replace(0, np.nan)

        pr = (series - rolling_min) / denom
        return pr * 100

    short = percent_rank(roc, lookback)
    medium = percent_rank(roc, lookback * factor)
    long = percent_rank(roc, lookback * factor * factor)

    # --- 3. Weighted Composite ---
    weight_short = factor * factor
    weight_medium = factor
    weight_long = 1

    total_weight = weight_short + weight_medium + weight_long

    ultimate = (
        (short * weight_short) +
        (medium * weight_medium) +
        (long * weight_long)
    ) / total_weight

    # --- 4. Smoothing ---
    ultimate_smoothed = ultimate.rolling(window=smooth, min_periods=smooth).mean()

    # --- 5. Signal Zones ---
    signal = np.where(
        ultimate_smoothed > overbought,
        1,   # overbought
        np.where(ultimate_smoothed < oversold, -1, 0)
    )

    return pd.DataFrame({
        "ultimate_c": ultimate_smoothed,
        "ultimate_signal": signal
    }, index=df.index)