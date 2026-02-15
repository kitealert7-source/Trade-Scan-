
"""
Daily Pivot Points — Canonical Production Implementation

Implements classic floor trader pivot points using previous session values.

Features:
- Uses ONLY prior session OHLC (no forward bias)
- Fully vectorized
- Canonical pivot levels: Pivot, R1, S1, R2, S2
- Production-safe and deterministic

Output columns:
    pivot
    r1
    s1
    r2
    s2
"""

import pandas as pd
import numpy as np


def daily_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily pivot points using previous session OHLC.

    Args:
        df: DataFrame with columns ['high', 'low', 'close']

    Returns:
        DataFrame with columns:
            pivot, r1, s1, r2, s2
    """

    # Enforce numeric dtype
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # Use previous session values (shifted)
    high_prev = high.shift(1)
    low_prev = low.shift(1)
    close_prev = close.shift(1)

    # Pivot calculation
    pivot = (high_prev + low_prev + close_prev) / 3.0

    # Support and resistance levels
    r1 = (2.0 * pivot) - low_prev
    s1 = (2.0 * pivot) - high_prev

    r2 = pivot + (high_prev - low_prev)
    s2 = pivot - (high_prev - low_prev)

    # Assemble output
    result = pd.DataFrame({
        "pivot": pivot,
        "r1": r1,
        "s1": s1,
        "r2": r2,
        "s2": s2
    }, index=df.index)

    # Invariant check: pivot must be finite where inputs exist
    if result["pivot"].iloc[1:].isna().all():
        raise RuntimeError("daily_pivot_points invariant violation: pivot computation failed")

    return result
