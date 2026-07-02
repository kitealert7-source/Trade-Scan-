"""
KC Bands — asymmetric EMA-of-High / EMA-of-Low channel with ATR width
---------------------------------------------------------------------
Purpose:
    Channel "stretch reference" for mean-reversion / breakout signals.
    Re-engineered Bollinger alternative (StatOasis, 2026): fixes the two
    structural flaws of close-based symmetric bands —
      (1) both BB bands derive from the same input (close); here the upper
          band tracks EMA(high) and the lower tracks EMA(low) independently,
          so the channel is asymmetric and a one-sided spike moves only its
          own side;
      (2) std-dev over-reacts to a single outlier bar; ATR (an average of
          ranges) replaces it as the width term.
    A final s-bar SMA over the raw bands suppresses flicker.

Outputs (single pass, one DataFrame):
    kc_upper   — SMA(EMA(high, n) + mult*ATR(a), s)          [price units]
    kc_lower   — SMA(EMA(low,  n) - mult*ATR(a), s)          [price units]
    kc_pct_c   — (close - lower) / (upper - lower) * 100     [graded; may
                 exceed 0-100: -45 = deep below band, +106 = above band]
    kc_width_c — (upper - lower) / close * 100                [vol-state %]

Defaults are GENERIC (concept-harvest posture, 2026-07-02): no parity with
the source's swept picks is intended; the pipeline verifies on our data.

Safe:
    - No division by zero (degenerate zero-range channel -> NaN pct_c)
    - No lookahead (EMA/SMA/ATR are backward-looking; ATR uses shift(1))
    - Fully vectorized, O(n)
    - Input not mutated
"""

import pandas as pd
import numpy as np

# Declared-signal contract value; must also be present in the
# tools/semantic_validator.py _ALLOWED_PRIMITIVES allowlist before any
# directive DECLARES this module (protected-surface edit, operator-gated).
SIGNAL_PRIMITIVE = "kc_band_stretch"


def kc_bands(
    df: pd.DataFrame,
    ema_window: int = 20,
    atr_period: int = 30,
    atr_mult: float = 1.0,
    smooth: int = 3,
) -> pd.DataFrame:

    for col in ("high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain '{col}' column")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # --- 1. Independent per-side centerlines ---
    ema_h = high.ewm(span=ema_window, adjust=False).mean()
    ema_l = low.ewm(span=ema_window, adjust=False).mean()

    # --- 2. ATR width term (Wilder, matching keltner_channel.py) ---
    high_low = high - low
    high_close = (high - close.shift(1)).abs()
    low_close = (low - close.shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / atr_period, adjust=False).mean()

    # --- 3. Raw bands + flicker smoothing ---
    kc_upper = (ema_h + atr_mult * atr).rolling(smooth, min_periods=smooth).mean()
    kc_lower = (ema_l - atr_mult * atr).rolling(smooth, min_periods=smooth).mean()

    # --- 4. Derived outputs ---
    channel_range = (kc_upper - kc_lower).replace(0, np.nan)
    kc_pct_c = (close - kc_lower) / channel_range * 100.0
    kc_width_c = (kc_upper - kc_lower) / close.replace(0, np.nan) * 100.0

    return pd.DataFrame(
        {
            "kc_upper": kc_upper,
            "kc_lower": kc_lower,
            "kc_pct_c": kc_pct_c,
            "kc_width_c": kc_width_c,
        },
        index=df.index,
    )
