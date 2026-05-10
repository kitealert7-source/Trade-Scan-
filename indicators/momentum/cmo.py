"""
Chande Momentum Oscillator (CMO) — Pine ta.cmo() port.

Formula (matches Pine v6 ta.cmo):
    diff      = close - close.shift(1)
    gain      = max(diff, 0)
    loss      = max(-diff, 0)
    sum_gain  = sum(gain) over `period` bars
    sum_loss  = sum(loss) over `period` bars
    CMO       = 100 * (sum_gain - sum_loss) / (sum_gain + sum_loss)

Range: [-100, +100]. Positive readings indicate net upward momentum, negative
readings net downward. Unlike RSI, CMO is symmetric around zero — there is no
50 midline.

Differs from ROC: ROC measures the price change ratio over a fixed window,
CMO measures the relative strength of net gains vs net losses bar-by-bar.
"""

import pandas as pd
import numpy as np

# --- Semantic Contract ---
SIGNAL_PRIMITIVE = "momentum_cmo"
PIVOT_SOURCE = "none"


def cmo(series: pd.Series, period: int = 9) -> pd.Series:
    """
    Calculate Chande Momentum Oscillator.

    Args:
        series: price series (typically close).
        period: lookback bars for sum_gain / sum_loss (default 9, Pine default).

    Returns:
        CMO series in [-100, +100]. NaN until `period` bars have accumulated.
    """
    series = series.astype(float)

    diff = series.diff()
    gain = diff.clip(lower=0.0)
    loss = (-diff).clip(lower=0.0)

    sum_gain = gain.rolling(period, min_periods=period).sum()
    sum_loss = loss.rolling(period, min_periods=period).sum()

    denom = (sum_gain + sum_loss).replace(0, np.nan)
    cmo_series = 100.0 * (sum_gain - sum_loss) / denom

    # Scale invariant
    max_abs = cmo_series.abs().max(skipna=True)
    if pd.notna(max_abs) and max_abs > 100.0001:
        raise RuntimeError(
            f"cmo invariant violation: |max| {max_abs:.6f} exceeds expected "
            f"100. Numerical instability suspected."
        )

    return cmo_series
