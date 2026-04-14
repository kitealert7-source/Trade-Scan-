import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "atr_rolling_percentile"
PIVOT_SOURCE = "none"


def atr_percentile(
    atr_series: pd.Series,
    window: int = 100
) -> pd.Series:
    """
    Calculate rolling percentile rank of ATR within a lookback window.

    Percentile definition:
        Percentile rank of the most recent ATR value
        within the rolling window.

    Output Scale: 0.0–1.0
        Use atr_percentile * 100 for percentage comparison.

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

    # -------------------------------------------------------------------------
    # GOVERNANCE: Scale Invariant Check
    # Output must be strictly in [0.0, 1.0] range.
    # -------------------------------------------------------------------------
    max_val = percentile.max(skipna=True)
    if pd.notna(max_val) and max_val > 1.0001:
        raise RuntimeError(
            f"atr_percentile invariant violation: max value {max_val:.6f} "
            f"exceeds expected 0.0–1.0 scale. Scale corruption detected."
        )

    return percentile