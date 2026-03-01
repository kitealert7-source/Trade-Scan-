import pandas as pd
import numpy as np


def atr_percentile(
    atr_series: pd.Series,
    window: int = 100
) -> pd.Series:
    """
    Calculate rolling percentile rank of ATR within a lookback window.

    Percentile definition:
        Percentile rank of the most recent ATR value
        within the rolling window (0.0 → 1.0 scale).

    Args:
        atr_series: pd.Series of ATR values
        window: Rolling lookback period

    Returns:
        pd.Series of percentile values (float, 0.0–1.0)
    """

    atr_series = atr_series.astype(float)

    def percentile_last(x):
        # Percentile rank of latest value within window
        return np.sum(x <= x[-1]) / len(x)

    percentile = atr_series.rolling(
        window=window,
        min_periods=window  # strict window — avoids unstable early values
    ).apply(percentile_last, raw=True)

    return percentile