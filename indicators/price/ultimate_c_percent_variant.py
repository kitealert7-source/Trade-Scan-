import pandas as pd
import numpy as np


def ultimate_c_percent_variant(
    df: pd.DataFrame,
    mode: str = "baseline"
) -> pd.DataFrame:

    if "close" not in df.columns:
        raise ValueError("DataFrame must contain 'close' column")

    close = df["close"].astype(float)

    # --- Preset configurations ---
    if mode == "fast":
        roc_period = 1
        lookback = 5
        factor = 2
        smooth = 1
        overbought = 80
        oversold = 20

    elif mode == "balanced":
        roc_period = 1
        lookback = 5
        factor = 2
        smooth = 2
        overbought = 80
        oversold = 20

    elif mode == "slow":
        roc_period = 1
        lookback = 7
        factor = 2
        smooth = 3
        overbought = 75
        oversold = 25

    else:  # baseline (same as original)
        roc_period = 1
        lookback = 5
        factor = 2
        smooth = 3
        overbought = 75
        oversold = 25

    # --- 1. Rate of Change ---
    roc = close.pct_change(periods=roc_period) * 100

    # --- 2. Percent Rank ---
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

    # --- 3. Weighted composite ---
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

    # --- 5. Signal zones ---
    signal = np.where(
        ultimate_smoothed > overbought,
        1,
        np.where(ultimate_smoothed < oversold, -1, 0)
    )

    return pd.DataFrame({
        "ultimate_c": ultimate_smoothed,
        "ultimate_signal": signal
    }, index=df.index)