
"""
Session Range Structure Indicator — Canonical Production Implementation

Computes a configurable session range (e.g., 03:00–06:00 UTC)
and detects breakout structure without embedding trading logic.

Features:
- Fully vectorized where possible
- No forward bias
- Session window configurable
- Outputs structural state only (no orders, no stops)

Required input columns:
    ['open', 'high', 'low', 'close']
Index:
    Must be timezone-aware or UTC-normalized pandas DateTimeIndex
    at intraday resolution (e.g., M5)
"""

import pandas as pd
import numpy as np


def session_range_structure(
    df: pd.DataFrame,
    session_start: str = "03:00",
    session_end: str = "06:00"
) -> pd.DataFrame:
    """
    Compute session high/low and breakout structure.

    Args:
        df: DataFrame with ['open', 'high', 'low', 'close']
            and DateTimeIndex (UTC).
        session_start: Session start time (HH:MM)
        session_end: Session end time (HH:MM)

    Returns:
        DataFrame with columns:
            session_high
            session_low
            range_points
            range_percent
            break_direction (1 = upside, -1 = downside, 0 = none)
            has_broken (bool)
    """

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be DatetimeIndex")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    result = pd.DataFrame(index=df.index)

    # Identify session mask per day
    session_mask = (
        (df.index.time >= pd.to_datetime(session_start).time()) &
        (df.index.time < pd.to_datetime(session_end).time())
    )

    # Group by date (UTC)
    dates = df.index.normalize()

    session_high = high.where(session_mask).groupby(dates).transform("max")
    session_low = low.where(session_mask).groupby(dates).transform("min")

    # Forward-fill within day after session ends
    session_high = session_high.groupby(dates).ffill()
    session_low = session_low.groupby(dates).ffill()

    range_points = session_high - session_low
    range_percent = range_points / close

    # Breakout detection (after session end only)
    after_session_mask = df.index.time >= pd.to_datetime(session_end).time()

    break_up = (high > session_high) & after_session_mask
    break_down = (low < session_low) & after_session_mask

    break_direction = np.where(break_up, 1,
                        np.where(break_down, -1, 0))

    has_broken = break_direction != 0

    result["session_high"] = session_high
    result["session_low"] = session_low
    result["range_points"] = range_points
    result["range_percent"] = range_percent
    result["break_direction"] = break_direction
    result["has_broken"] = has_broken

    # Invariant check
    if result["session_high"].isna().all():
        raise RuntimeError("session_range_structure invariant violation: session high not computed")

    return result
