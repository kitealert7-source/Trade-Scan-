"""
Rolling AR(1) Half-Life — local mean-reversion speed of a price-like series

Estimates, within each rolling window, the half-life (in bars) of reversion
toward the local mean via the discrete AR(1) / Ornstein-Uhlenbeck fit:

    y_t = log(series_t)
    dy_t = a + b * y_{t-1} + eps     (OLS over the window)
    half_life = -ln(2) / ln(1 + b)   for -1 < b < 0

Interpretation
--------------
small HL      -> fast local reversion (bars)
large HL      -> slow local reversion
+inf          -> NON-REVERTING window (b >= 0; drift/trend locally)
1.0 (floor)   -> overcorrecting/oscillatory window (b <= -1); reversion is
                 faster than one bar, the AR(1) half-life concept saturates
NaN           -> not estimable (warmup, NaN in window, zero variance)

Timescale note (2026-06-12): this is the LOCAL, execution-TF statistic. It is
NOT the screener's `half_life_days` (daily TF, 252d lookback) — that one runs
~1,300+ 15m bars and is two orders of magnitude above this strategy family's
trade horizon (champion corpus: median hold 14 bars / p95 28 bars). Thresholds
calibrated here are in BARS of the input series' timeframe.

Output
------
Series of half-life values in bars, indexed like the input. First `window`
bars are NaN. +inf is a MEANINGFUL value (non-reverting), distinct from NaN
(unknown): consumers that gate on "too slow" should treat inf as blockable
and NaN as fail-open.
"""

import numpy as np
import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "rolling_half_life_speed"
PIVOT_SOURCE = "none"

__all__ = ["rolling_half_life"]


def rolling_half_life(
    series: pd.Series,
    window: int = 100,
) -> pd.Series:
    """Compute rolling AR(1) half-life (bars) on log of a price-like series.

    Args:
        series: pandas Series of strictly positive prices/ratios.
        window: number of (y_{t-1}, dy_t) pairs per fit (default 100); each
            estimate uses window+1 log-levels ending at the output bar.

    Returns:
        pandas Series of half-life values (bars), indexed like the input.
        NaN for warmup / NaN windows / zero-variance windows; +inf for
        non-reverting windows (b >= 0); floored at 1.0 for b <= -1.
    """
    series = pd.to_numeric(series, errors="coerce").astype(float)
    y = np.log(series.where(series > 0))

    def _hl(x):
        if np.any(np.isnan(x)):
            return np.nan
        ylag = x[:-1]
        dy = np.diff(x)
        ym = ylag - ylag.mean()
        den = float((ym ** 2).sum())
        if den <= 0.0:
            return np.nan
        b = float((ym * (dy - dy.mean())).sum() / den)
        if b >= 0.0:
            return np.inf          # non-reverting (meaningful, not unknown)
        if b <= -1.0:
            return 1.0             # overcorrecting: saturate at 1 bar
        return float(-np.log(2.0) / np.log(1.0 + b))

    # window+1 levels -> window (lag, diff) pairs per estimate.
    return y.rolling(window=window + 1, min_periods=window + 1).apply(_hl, raw=True)
