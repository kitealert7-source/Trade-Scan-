"""
pearson_correlation.py

Rolling Pearson correlation between two return series.

Purpose
-------
Measure the linear co-movement of two price series over a rolling window.
For 2-leg basket strategies (H2/H3 family), the correlation between the
two legs' returns determines whether they have independent drivers (low
|rho| → winner/loser asymmetry emerges, H3 pyramid mechanic has room
to work) or shared drivers (high |rho| → legs co-move, no clean
winner-loser split, H3 stalls).

Used by
-------
- tools/factors/fx_correlation_matrix.py — offline generator that
  computes all pair-pair-timeframe correlations across the FX universe
  and writes the result to data_root/SYSTEM_FACTORS/FX_CORRELATION_MATRIX/.
- tools/recycle_rules/h2_recycle_v5.py — runtime gate that blocks
  pyramid trigger when the leg-pair correlation is outside the
  configured entry band.

Implementation notes
--------------------
- Computes log returns from input prices, then rolling Pearson
  correlation of the two return series.
- Lookahead-safe (only past data used, no centering).
- Vectorized (pandas .rolling().corr()).
- Returns NaN for the first `window` bars (warmup); caller handles.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def pearson_correlation(
    series_a: pd.Series,
    series_b: pd.Series,
    window: int = 200,
) -> pd.Series:
    """Rolling Pearson correlation of log returns of two price series.

    Args:
        series_a: price series (e.g. close), indexed by timestamp.
        series_b: price series (e.g. close), indexed by timestamp. Index
            must align with series_a; misaligned rows produce NaN in the
            output.
        window: rolling window length in bars (default 200). Output is
            NaN for the first `window` bars (warmup).

    Returns:
        pd.Series indexed identically to series_a, with values in
        [-1.0, 1.0] (or NaN during warmup / missing data). Negative
        values = anti-correlated returns; positive = co-moving;
        zero = independent.

    Notes:
        - Uses log returns: log(P_t / P_{t-1}). NaN when price <= 0.
        - Output is the Pearson coefficient of the LAST `window` returns,
          not prices directly. Correlation of returns is the standard
          way to measure co-movement strength (price-level correlation
          is dominated by trend, not local relationship).
    """
    if window < 2:
        raise ValueError(f"pearson_correlation.window must be >= 2; got {window}")

    a = pd.to_numeric(series_a, errors="coerce").astype(float)
    b = pd.to_numeric(series_b, errors="coerce").astype(float)

    # Log returns; NaN-safe under zero/negative prices.
    log_a = np.log(a.where(a > 0))
    log_b = np.log(b.where(b > 0))
    ret_a = log_a.diff()
    ret_b = log_b.diff()

    # Rolling Pearson on the two return series.
    corr = ret_a.rolling(window=window, min_periods=window).corr(ret_b)

    return corr


__all__ = ["pearson_correlation"]
