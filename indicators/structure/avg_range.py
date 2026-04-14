import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "rolling_range_mean"
PIVOT_SOURCE = "none"


def avg_range(df: pd.DataFrame, window: int = 5, min_periods: int = 3) -> pd.Series:
    """
    Compute rolling average of bar range (high - low).

    Args:
        df:          DataFrame with 'high' and 'low' columns.
        window:      Rolling lookback period.
        min_periods: Minimum number of observations required.

    Returns:
        pd.Series of rolling average bar ranges.
    """
    bar_range = (df['high'] - df['low']).astype(float)
    return bar_range.rolling(window=window, min_periods=min_periods).mean()
