"""
Average Directional Index (ADX) — Wilder's RMA Implementation

Faithful port of Pine's `ta.adx()` and `ta.dmi()`, which use Wilder's RMA
(Running Moving Average) for ALL smoothing steps (TR, +DM, -DM, and ADX
itself).

Difference vs indicators.structure.adx
--------------------------------------
The existing adx in this repo uses pandas `ewm(span=period, adjust=False)`
which is standard EMA, NOT Wilder's. For period=14:

    Wilder's RMA (this module): alpha = 1/14 ≈ 0.0714
    EMA span=14 (standard adx): alpha = 2/15 ≈ 0.1333

EMA reacts ~2x faster than Wilder's RMA at the same nominal period. Same
price data → different ADX values → different threshold semantics.

Pine's "ADX > 15" (Wilder's) is roughly equivalent to EMA-ADX "ADX > 20-25"
because the EMA version reaches higher values faster on the same data.

Use this module when calibrating against Pine ta.adx() / ta.dmi() baselines.
The standard adx module is preserved for backward compatibility with
strategies that use it.

Empirical: in the KALFLIP S01 V2 sweep, Pine's adx>15 threshold acted as
"weak trend" gate; the EMA-based adx at threshold 15 was too loose, and
threshold 25 was needed to achieve similar selectivity. With Wilder's RMA,
threshold 15 should align with Pine's behavior.
"""

import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "adx_wilder_trend_strength"
PIVOT_SOURCE = "none"

__all__ = ["adx_wilder"]


def adx_wilder(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Compute ADX using Wilder's RMA smoothing (matches Pine ta.adx() / ta.dmi()).

    Algorithm:
      1. True Range:    max(H-L, |H-prev_C|, |L-prev_C|)
      2. +DM, -DM:      directional movement (standard Wilder)
      3. Smoothing:     Wilder's RMA on TR, +DM, -DM (alpha = 1/period)
      4. +DI = 100 * smoothed(+DM) / smoothed(TR)
         -DI = 100 * smoothed(-DM) / smoothed(TR)
      5. DX = 100 * |+DI - -DI| / (+DI + -DI)
      6. ADX = Wilder's RMA of DX (alpha = 1/period)

    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        period: Lookback period (default 14, Wilder's standard)

    Returns:
        pandas Series of ADX values (0-100 scale, higher = stronger trend)
    """

    # True Range (same as standard ADX)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement (same as standard ADX)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    # ===== KEY DIFFERENCE: Wilder's RMA (alpha = 1/period) =====
    # Pine ta.dmi() / ta.adx() uses Wilder's smoothing, NOT EMA span.
    alpha = 1.0 / period

    smoothed_tr        = true_range.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smoothed_plus_dm   = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smoothed_minus_dm  = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    # NaN safety: replace zero smoothed TR with nan to avoid inf
    smoothed_tr_safe = smoothed_tr.replace(0, np.nan)

    # Directional Indicators
    plus_di  = 100.0 * (smoothed_plus_dm  / smoothed_tr_safe)
    minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr_safe)

    # DX (Directional Index)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)

    # ADX = Wilder's RMA of DX (matches Pine convention)
    adx_series = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    # -------------------------------------------------------------------------
    # GOVERNANCE: Scale Invariant Check
    # ADX must be in [0, 100] range. Outliers indicate computation error.
    # -------------------------------------------------------------------------
    max_val = adx_series.max(skipna=True)
    if pd.notna(max_val) and max_val > 100.0001:
        raise RuntimeError(
            f"adx_wilder invariant violation: max value {max_val:.6f} "
            f"exceeds expected 0-100 scale. Numerical instability suspected."
        )

    return adx_series
