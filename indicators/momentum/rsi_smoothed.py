"""
Smoothed RSI -- SMA(N) of RSI(P)

Purpose
-------
Combines a fast RSI signal (typically RSI(2) per Connors convention) with an
SMA over the last N RSI values to dampen single-bar oscillator jitter while
preserving fast response. Used as a momentum-confirmation gate for trend-
following strategies (e.g., flip-style entries).

Default period=2 follows Larry Connors' fast-RSI convention.
Default smoothing=3 averages T, T-1, T-2 RSI values.

Output Scale: 0.0-100.0 (same as raw RSI)
"""

import pandas as pd
import numpy as np

from indicators.momentum.rsi import rsi

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "rsi_smoothed_threshold"
PIVOT_SOURCE = "none"

__all__ = ["rsi_smoothed"]


def rsi_smoothed(
    series: pd.Series,
    period: int = 2,
    smoothing: int = 3
) -> pd.Series:
    """
    Compute SMA-smoothed RSI.

    Args:
        series: pandas Series of prices
        period: RSI lookback period (default 2 -- Connors convention)
        smoothing: SMA window applied to RSI (default 3 -- T, T-1, T-2)

    Returns:
        pandas Series containing SMA-smoothed RSI values (0.0-100.0)
    """

    rsi_raw = rsi(series, period=period)

    smoothed = rsi_raw.rolling(
        window=smoothing,
        min_periods=smoothing  # strict window -- no partial-window output
    ).mean()

    # -------------------------------------------------------------------------
    # GOVERNANCE: Scale Invariant Check
    # Output must remain in [0.0, 100.0] range (raw RSI scale, preserved by SMA).
    # -------------------------------------------------------------------------
    max_val = smoothed.max(skipna=True)
    if pd.notna(max_val) and max_val > 100.0001:
        raise RuntimeError(
            f"rsi_smoothed invariant violation: max value {max_val:.6f} "
            f"exceeds expected 0.0-100.0 scale. Scale corruption detected."
        )

    return smoothed
