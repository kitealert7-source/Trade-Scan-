"""
SuperTrend — ATR trailing channel with direction state
------------------------------------------------------
Purpose:
    Trend-following flip indicator. Basic bands at (high+low)/2 +/- mult*ATR
    ratchet toward price (an uptrend's stop line never moves down; a
    downtrend's never moves up) and the direction flips when the close
    crosses the active band.

Outputs (single pass, one DataFrame):
    supertrend — the active stop/trail line                    [price units]
    st_dir     — direction state: +1 uptrend (line below price),
                 -1 downtrend (line above price)               [-1 / +1]
    st_upper   — final (ratcheted) upper band                  [price units]
    st_lower   — final (ratcheted) lower band                  [price units]

Defaults are GENERIC textbook SuperTrend (period=10, multiplier=3.0) —
concept-harvest posture 2026-07-02, no source parity intended. Multi-instance
use (e.g. fast 10/2 + slow 30/4 dual-SuperTrend) is parameterization at the
strategy/directive level per SOP_INDICATOR §11.3, NOT separate modules.

Safe:
    - No lookahead: recursion is strictly forward (bar i uses bar i-1 state);
      appending future bars never changes past values
    - Warmup rows (ATR seed) emitted as NaN line / 0 direction until the
      first full ATR window
    - Single O(n) loop over numpy arrays (governance: no nested loops)
    - Input not mutated
"""

import pandas as pd
import numpy as np

# Declared-signal contract value; pending batch addition to
# tools/semantic_validator.py _ALLOWED_PRIMITIVES (protected surface,
# operator-approved to land at end of the 2026-07-02 authoring batch).
SIGNAL_PRIMITIVE = "supertrend_flip"


def supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:

    for col in ("high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain '{col}' column")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # --- 1. ATR (Wilder, matching keltner_channel.py / kc_bands.py) ---
    high_low = high - low
    high_close = (high - close.shift(1)).abs()
    low_close = (low - close.shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()

    # --- 2. Basic bands ---
    mid = (high + low) / 2.0
    basic_upper = (mid + multiplier * atr).to_numpy()
    basic_lower = (mid - multiplier * atr).to_numpy()
    close_np = close.to_numpy()

    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st_line = np.full(n, np.nan)
    st_dir = np.zeros(n, dtype=np.int64)  # 0 during warmup

    # --- 3. Ratchet + flip recursion (single O(n) loop; bar i reads only
    #        bar i-1 state -> forward-only, lookahead-free) ---
    start = period  # let the Wilder EMA seed before emitting state
    if n > start:
        final_upper[start] = basic_upper[start]
        final_lower[start] = basic_lower[start]
        st_dir[start] = 1 if close_np[start] > basic_upper[start] else -1
        st_line[start] = (
            final_lower[start] if st_dir[start] == 1 else final_upper[start]
        )

    for i in range(start + 1, n):
        # band ratchet: tighten toward price, release only after a close-through
        if basic_upper[i] < final_upper[i - 1] or close_np[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        if basic_lower[i] > final_lower[i - 1] or close_np[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # direction flip on close crossing the active band
        if st_dir[i - 1] == -1:
            st_dir[i] = 1 if close_np[i] > final_upper[i] else -1
        else:
            st_dir[i] = -1 if close_np[i] < final_lower[i] else 1

        st_line[i] = final_lower[i] if st_dir[i] == 1 else final_upper[i]

    return pd.DataFrame(
        {
            "supertrend": st_line,
            "st_dir": st_dir,
            "st_upper": final_upper,
            "st_lower": final_lower,
        },
        index=df.index,
    )
