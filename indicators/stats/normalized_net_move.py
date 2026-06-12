"""
Normalized Net Move — vol-scaled trailing directional displacement

For each bar, the ABSOLUTE NET log-return over the trailing `window` bars,
scaled by the series' own causal volatility:

    r_t   = log(p_t / p_{t-1})
    net_t = | sum(r_{t-window+1} .. r_t) |
    nnm_t = net_t / (sigma_t * sqrt(window))

where sigma_t is the EXPANDING (run-to-date) population std of r up to t
(min_periods = `min_vol_obs`) — strictly causal, no full-run lookahead.

Interpretation
--------------
~0        -> no net displacement (oscillation/noise; vol without direction)
~1        -> displacement consistent with a random walk at current vol
>= 2      -> large directional repricing (information move) — the population
             a mean-reversion entry should NOT fade (2026-06-12 FX-IDX
             stuck-entry characterization: cycle PnL deteriorates
             monotonically with this statistic in ALL four pair classes)

Distinct from volatility-regime measures: this is net DISPLACEMENT, not
variance — high vol with zero drift scores ~0 here.

Output
------
Series of nnm values, indexed like the input. NaN until both the rolling
window and the expanding vol estimate are available, and wherever sigma is 0
(fail-open convention: consumers gating on "too large" must not block on NaN).
"""

import numpy as np
import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "normalized_net_move_displacement"
PIVOT_SOURCE = "none"

__all__ = ["normalized_net_move"]


def normalized_net_move(
    series: pd.Series,
    window: int = 12,
    min_vol_obs: int = 100,
) -> pd.Series:
    """Vol-scaled trailing net displacement of a price-like series.

    Args:
        series: pandas Series of strictly positive prices.
        window: trailing bars for the net move (default 12).
        min_vol_obs: minimum return observations before the expanding vol
            (and therefore the output) is defined (default 100).

    Returns:
        pandas Series of normalized net-move values (>= 0), NaN during
        warmup or zero-vol stretches.
    """
    series = pd.to_numeric(series, errors="coerce").astype(float)
    r = np.log(series.where(series > 0)).diff()

    net = r.rolling(window=window, min_periods=window).sum().abs()
    sigma = r.expanding(min_periods=min_vol_obs).std(ddof=0)
    sigma = sigma.where(sigma > 0)  # zero-vol -> NaN (fail-open downstream)

    return net / (sigma * np.sqrt(window))
