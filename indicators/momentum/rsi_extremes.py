"""
RSI Rolling Extremes — floor and ceiling over a lookback window.

Used for momentum divergence detection: compares current RSI
to its recent min/max to determine whether momentum confirms
a price extreme.
"""
import pandas as pd
from indicators.momentum.rsi import rsi as compute_rsi


def rsi_extremes(
    series: pd.Series,
    period: int = 14,
    lookback: int = 20,
    shift: int = 1,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Compute RSI and its rolling floor/ceiling.

    Args:
        series: Close price series.
        period: RSI period (default 14).
        lookback: Rolling window for min/max (default 20).
        shift: Bars to shift the floor/ceiling (default 1,
               excludes current bar for divergence detection).

    Returns:
        tuple of (rsi, rsi_floor, rsi_ceil):
            rsi       : RSI values
            rsi_floor : Rolling minimum of RSI over lookback, shifted
            rsi_ceil  : Rolling maximum of RSI over lookback, shifted
    """
    rsi_vals = compute_rsi(series, period=period)
    rsi_floor = rsi_vals.rolling(lookback).min().shift(shift)
    rsi_ceil = rsi_vals.rolling(lookback).max().shift(shift)
    return rsi_vals, rsi_floor, rsi_ceil
