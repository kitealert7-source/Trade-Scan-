"""
Directional Movement Index (+DI / -DI) — Pine ta.dmi() port using Wilder's RMA.

Sibling module to `adx_wilder.py`: same Wilder smoothing math, but exposes the
two directional indicator components instead of folding them into a single ADX
series. Used by strategies that gate on raw DI+ vs DI- spread (e.g. Pine's
`(di_plus - di_minus) >= threshold` long pass).

Wilder's RMA convention:
    Pine ta.dmi() / ta.adx() smooth True Range, +DM, and -DM with Wilder's
    Running Moving Average (alpha = 1/period), NOT pandas-default EMA span.
    For period=14: Wilder alpha ≈ 0.0714 vs EMA span=14 alpha ≈ 0.1333. EMA
    reacts ~2x faster on the same data; Pine thresholds calibrated against
    the EMA path will be too loose.

If you also need the ADX series, call adx_wilder() separately — it uses the
same intermediate quantities but applies a final Wilder smoothing to DX.

Algorithm:
    1. True Range:    max(H-L, |H-prev_C|, |L-prev_C|)
    2. +DM, -DM:      directional movement (standard Wilder rules)
    3. Smoothing:     Wilder's RMA on TR, +DM, -DM (alpha = 1/period)
    4. +DI = 100 * smoothed(+DM) / smoothed(TR)
       -DI = 100 * smoothed(-DM) / smoothed(TR)
"""

import pandas as pd
import numpy as np

# --- Semantic Contract ---
SIGNAL_PRIMITIVE = "dmi_wilder_directional"
PIVOT_SOURCE = "none"

__all__ = ["dmi_wilder"]


def dmi_wilder(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.DataFrame:
    """
    Compute +DI / -DI using Wilder's RMA smoothing (matches Pine ta.dmi()).

    Args:
        high: High prices series.
        low:  Low prices series.
        close: Close prices series.
        period: Lookback period (default 14, Wilder's standard).

    Returns:
        DataFrame indexed identically to the input series with two columns:
            plus_di:  +DI in [0, 100]
            minus_di: -DI in [0, 100]
    """

    # True Range (same as adx_wilder)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement (standard Wilder rules)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
        dtype=float,
    )

    # Wilder's RMA: alpha = 1/period
    alpha = 1.0 / period
    smoothed_tr = true_range.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    smoothed_tr_safe = smoothed_tr.replace(0, np.nan)

    plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr_safe)
    minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr_safe)

    # Scale invariant — DI components must be in [0, 100]
    for name, ser in (("plus_di", plus_di), ("minus_di", minus_di)):
        m = ser.max(skipna=True)
        if pd.notna(m) and m > 100.0001:
            raise RuntimeError(
                f"dmi_wilder invariant violation: max {name} = {m:.6f} "
                f"exceeds expected 0-100 scale. Numerical instability suspected."
            )

    return pd.DataFrame(
        {"plus_di": plus_di, "minus_di": minus_di},
        index=high.index,
    )
