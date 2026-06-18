"""
Ratio-Hedged Spread Z-Score — Cross-symbol utility for cointegration pair strategies

Pure cross-symbol indicator-as-utility for basket strategies. Computes the z-score
of a ratio-hedged spread A - r_bar*B where r_bar = SMA(A/B, N).

Distinct from rolling_zscore (single-series) and cointegration_state (Pearson
beta-hedged spread from OLS regression). Used by Pine-port basket strategies
(e.g., COINTREV_V3) that need a hedge ratio updated from rolling price ratios,
not OLS regression.

Source: ports the Pine z_r computation from Pine Indicators/Cointegrated Pair
Strategy.txt (companion to the Cointegrated Pair Overlay indicator).

Architectural note: this utility is invoked from recycle rule code (which has
access to both leg DataFrames), not from a strategy's prepare_indicators(df)
which only sees one symbol's df. Stage-0.5 Inline Indicator Detection does not
apply to recycle rules — they orchestrate cross-leg logic by design.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "ratio_hedged_spread_zscore"
PIVOT_SOURCE = "none"


def ratio_hedged_spread_zscore(
    a_close: pd.Series,
    b_close: pd.Series,
    n: int = 100,
    n_meta: int | None = 100,
) -> pd.DataFrame:
    """Compute Pine-equivalent ratio-hedged spread z-score for a cointegrated pair.

    Args:
        a_close: Close prices of leg A (numerator in the price ratio)
        b_close: Close prices of leg B (denominator in the price ratio)
        n: Rolling window for both the hedge ratio (r_bar) and the spread's
            z-score normalization. Pine default = 100.
        n_meta: Centering window for z_r's own rolling mean. When set, the
            output also includes z_r_centered = z_r - SMA(z_r, n_meta).
            None or 0 disables Centered mode (returns z_r only). Pine
            default = 100 (Centered mode = "on").

    Returns:
        DataFrame with columns (indexed by a_close.index):
            ratio:        A / B (zero-denominator-safe raw price ratio) — the
                          canonical ratio series r_bar is averaged from.
                          Exposed so downstream consumers (e.g. the Hurst
                          entry filter) measure the SAME series the hedge
                          ratio derives from, never a reconstruction.
            r_bar:        Rolling mean of A/B over N bars (the hedge ratio)
            spread_r:     A - r_bar * B (the ratio-hedged spread series)
            z_r:          (spread_r - SMA(spread_r, N)) / STDEV(spread_r, N)
                          Pine-equivalent reversal signal.
            mean_zr:      SMA(z_r, n_meta) — only if n_meta is set
            z_r_centered: z_r - mean_zr — only if n_meta is set. Used as the
                          actual trigger series in Centered mode.

    Raises:
        ValueError: if the two input series do not share the same index.
        ValueError: if n < 2 or n_meta is not None and n_meta < 2.

    Notes:
        - Both inputs must be pre-aligned to the same index (intersect upstream).
        - Returns NaN for ~2N bars during warm-up (r_bar needs N bars, then
          spread_r's mean/std need another N).
        - Inf-safe: divide-by-zero in ratio (b_close==0) and z-score (std==0)
          collapse to NaN, never propagate as inf.
        - Population std (ddof=0) for consistency with rolling_zscore in this
          repo, and to match Pine's ta.stdev which uses population variance.
    """
    if n < 2:
        raise ValueError(f"n must be >= 2, got {n}")
    if n_meta is not None and n_meta < 2:
        raise ValueError(f"n_meta must be >= 2 or None, got {n_meta}")

    # Enforce float dtype
    a = a_close.astype(float)
    b = b_close.astype(float)

    # Defensive index alignment check
    if not a.index.equals(b.index):
        raise ValueError(
            f"a_close and b_close must share the same index "
            f"(len_a={len(a)}, len_b={len(b)})"
        )

    # Rolling ratio mean = hedge ratio. Zero-denom protection.
    ratio = a / b.replace(0, np.nan)
    r_bar = ratio.rolling(window=n, min_periods=n).mean()

    # Spread = A - r_bar * B. NaN-safe (NaN in r_bar propagates to NaN in spread_r).
    spread_r = a - r_bar * b

    # Z-score the spread
    spread_mean = spread_r.rolling(window=n, min_periods=n).mean()
    spread_std = spread_r.rolling(window=n, min_periods=n).std(ddof=0)
    spread_std = spread_std.replace(0, np.nan)  # safe div
    z_r = (spread_r - spread_mean) / spread_std
    z_r = z_r.replace([np.inf, -np.inf], np.nan)

    result = pd.DataFrame(
        {
            "ratio": ratio,
            "r_bar": r_bar,
            "spread_r": spread_r,
            "z_r": z_r,
        },
        index=a.index,
    )

    # Centered mode: z_r's own rolling mean for dynamic threshold adjustment
    if n_meta is not None and n_meta > 0:
        mean_zr = z_r.rolling(window=n_meta, min_periods=n_meta).mean()
        result["mean_zr"] = mean_zr
        result["z_r_centered"] = z_r - mean_zr

    return result
