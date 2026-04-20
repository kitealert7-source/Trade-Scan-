"""
ema_cross.py

Dual-EMA crossover state (fast vs slow).

Contract:
  - Raw EMA columns (`ema_fast`, `ema_slow`) are never masked.
  - `ema_cross_state` is deterministic:
        fast >  slow -> +1
        fast <  slow -> -1
        fast == slow -> carry forward previous state
        t < warmup   ->  0 (overrides)
  - Warmup = `slow` bars.
  - No aggregation. No thresholding.
"""

import numpy as np
import pandas as pd

SIGNAL_PRIMITIVE = "ema_cross"
PIVOT_SOURCE = "none"


def ema_cross(series_or_df, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    if fast <= 0 or slow <= 0:
        raise ValueError("ema_cross: fast and slow must be positive")
    if fast >= slow:
        raise ValueError(f"ema_cross: fast ({fast}) must be < slow ({slow})")

    # --- accept Series or engine-format DataFrame ---
    if isinstance(series_or_df, pd.DataFrame):
        if "close" not in series_or_df.columns:
            raise ValueError("ema_cross: DataFrame input requires 'close' column")
        series = series_or_df["close"]
    else:
        series = series_or_df

    series = series.astype(float)

    ema_fast = series.ewm(span=fast, adjust=False).mean().values
    ema_slow = series.ewm(span=slow, adjust=False).mean().values

    n = len(series)
    warmup = slow

    raw_state = np.zeros(n, dtype=np.int8)
    raw_state[ema_fast > ema_slow] = 1
    raw_state[ema_fast < ema_slow] = -1

    state = np.zeros(n, dtype=np.int8)
    prev = 0
    for i in range(n):
        if i < warmup:
            state[i] = 0
            prev = 0
            continue
        if raw_state[i] == 0:
            state[i] = prev
        else:
            state[i] = raw_state[i]
            prev = raw_state[i]

    return pd.DataFrame(
        {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_cross_state": state,
        },
        index=series.index,
    )


def time_requirement(params: dict, tf_minutes: int) -> int:
    slow = int(params.get("slow", 200))
    return slow * int(tf_minutes)
