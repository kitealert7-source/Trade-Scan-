"""
Hurst Exponent — R/S (Rescaled Range) Analysis on log returns

Faithful port of Pine v1.2 reference implementation. Computes Hurst exponent
within a rolling window using cumulative-deviation range divided by standard
deviation, scaled by log(N).

Interpretation (standard Hurst convention)
------------------------------------------
H < 0.5  → mean-reverting (anti-persistent)
H = 0.5  → random walk (Brownian)
H > 0.5  → persistent (trending)

Difference vs hurst_regime
--------------------------
This module uses R/S analysis (Mandelbrot's classical method), not the
lag-variance scaling that hurst_regime uses. The two are correlated but
NOT identical — they can produce different absolute Hurst values for the
same data, especially on shorter windows. Thresholds calibrated against
Pine R/S should use THIS module, not hurst_regime.

Empirical: in the KALFLIP S01 V2 sweep, Pine's R/S Hurst > 0.45 acted as
a working "above random walk" persistence filter; the lag-variance-based
hurst_regime at the same numeric threshold filtered out winning trades
instead. R/S vs lag-variance produce different Hurst values on the same
financial series.

Output
------
Series of Hurst exponent values (typical range 0.0 - 1.0).
Returns 0.5 (random-walk neutral) for warmup bars, NaN-containing windows,
or edge cases where R or S is non-positive.
"""

import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "hurst_rs_persistence"
PIVOT_SOURCE = "none"

__all__ = ["hurst_rs"]


def hurst_rs(
    series: pd.Series,
    window: int = 100
) -> pd.Series:
    """
    Compute Hurst exponent via R/S analysis on log returns.

    Algorithm (matches Pine v1.2 reference):
      1. Compute log returns: r_t = log(p_t / p_{t-1})
      2. Within each rolling window of N returns:
         a. mean   = mean(returns)
         b. dev    = returns - mean
         c. cumdev = cumsum(dev)
         d. R      = max(cumdev) - min(cumdev)
         e. S      = std(returns)  (population std, ddof=0, matches Pine)
         f. H      = log(R / S) / log(N)
      3. Returns 0.5 (neutral) for warmup, NaN windows, or R<=0 / S<=0

    Args:
        series: pandas Series of prices (typically close)
        window: number of returns in the rolling R/S window (default 100)

    Returns:
        pandas Series of Hurst exponent values, indexed identically to input.
        First (window-1) bars are NaN; subsequent bars are the H estimate.
    """

    series = pd.to_numeric(series, errors="coerce").astype(float)

    # Log returns: r_t = log(p_t / p_{t-1})
    log_returns = np.log(series / series.shift(1))

    def _rs(x):
        """R/S Hurst calculation on a single window of log returns."""
        # Skip windows with any missing data
        if np.any(np.isnan(x)):
            return 0.5

        N = len(x)
        if N < 2:
            return 0.5

        mean = np.mean(x)
        cumdev = np.cumsum(x - mean)
        R = cumdev.max() - cumdev.min()
        S = np.std(x, ddof=0)  # population std (divide by N), matches Pine

        # Numerical edge cases: constant series or zero range
        if S <= 0 or R <= 0:
            return 0.5

        return float(np.log(R / S) / np.log(N))

    hurst = log_returns.rolling(
        window=window,
        min_periods=window
    ).apply(_rs, raw=True)

    # -------------------------------------------------------------------------
    # GOVERNANCE: Scale Sanity Check
    # Hurst exponent is theoretically in [0, 1] but R/S analysis can produce
    # values slightly outside this range due to finite-sample noise. Extreme
    # outliers indicate computation error or pathological input data.
    # -------------------------------------------------------------------------
    finite_hurst = hurst.dropna()
    if len(finite_hurst) > 0:
        max_val = finite_hurst.max()
        min_val = finite_hurst.min()
        if max_val > 1.5 or min_val < -0.5:
            raise RuntimeError(
                f"hurst_rs invariant violation: H out of expected [-0.5, 1.5] "
                f"range. min={min_val:.4f}, max={max_val:.4f}. Numerical "
                f"instability suspected — verify input series quality."
            )

    return hurst
