"""
CCI — Commodity Channel Index (Lambert)
---------------------------------------
Purpose:
    Level-based oscillator: how far the source price sits from its own
    rolling mean, scaled by rolling mean absolute deviation.

        CCI = (src - SMA(src, period)) / (0.015 * MAD(src, period))

    Unbounded (typically ~[-300, +300]); signals are taken at LEVELS
    (e.g. cross of -95 upward), using the informative tail — not linearly.

Defaults are GENERIC textbook (period=20, typical price (H+L+C)/3,
Lambert constant 0.015) — concept-harvest posture 2026-07-02. The
StatOasis GBP demo's (H+L)/2 source is available via source="hl2"
(parameter, not a separate module, per SOP_INDICATOR §11).

Safe:
    - No division by zero (MAD == 0 -> NaN)
    - No lookahead (rolling ops backward-looking, min_periods=period)
    - Single rolling-apply with raw numpy (no nested Python loops)
    - Input not mutated
"""

import pandas as pd
import numpy as np

# Declared-signal contract value; pending batch addition to
# tools/semantic_validator.py _ALLOWED_PRIMITIVES (protected surface,
# operator-approved to land at end of the 2026-07-02 authoring batch).
SIGNAL_PRIMITIVE = "cci_threshold"

_LAMBERT_CONSTANT = 0.015


def cci(
    df: pd.DataFrame,
    period: int = 20,
    source: str = "typical",
) -> pd.Series:

    for col in ("high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain '{col}' column")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    if source == "typical":
        src = (high + low + close) / 3.0
    elif source == "hl2":
        src = (high + low) / 2.0
    elif source == "close":
        src = close
    else:
        raise ValueError(f"unknown source {source!r} (typical | hl2 | close)")

    sma = src.rolling(period, min_periods=period).mean()

    # rolling mean absolute deviation around each window's own mean
    mad = src.rolling(period, min_periods=period).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True
    )
    mad_safe = mad.replace(0, np.nan)

    return (src - sma) / (_LAMBERT_CONSTANT * mad_safe)
