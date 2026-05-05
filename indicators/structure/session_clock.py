"""
Session Clock — XAUUSD Liquidity-Driven Session Boundaries

Per-bar session classification, sequence numbering, running extremes, timing,
and day-of-week. Strict no-lookahead (running extremes via cummax/cummin per
session_seq).

Boundaries (UTC):
    asia:   00:00 - 07:00   (TOCOM core + SGE morning)
    london: 07:00 - 13:00   (London open through pre-NY, incl. AM fix)
    ny:     13:00 - 21:00   (NY open through COMEX pit close, incl. PM fix)
    none:   21:00 - 24:00   (dead zone, no tradeable session)

Output columns:
    session_id            : str   (asia | london | ny | none)
    session_seq           : int   (monotonic counter; one value per session occurrence)
    session_bar_idx       : int   (0-indexed bar position within current session_seq)
    session_pct_elapsed   : float (bar_idx / expected_session_bar_count; NaN in dead zone)
    day_of_week           : int   (0=Mon ... 6=Sun)
    session_high_running  : float (cummax of high within session_seq)
    session_low_running   : float (cummin of low within session_seq)
"""

import pandas as pd
import numpy as np

# --- Semantic Contract ---
SIGNAL_PRIMITIVE = "session_clock"
PIVOT_SOURCE = "none"

# --- XAU Liquidity-Driven Session Boundaries (UTC hours) ---
SESSION_BOUNDARIES = {
    "asia":   (0, 7),
    "london": (7, 13),
    "ny":     (13, 21),
}

# Expected 15M-bar count per session (drives pct_elapsed)
SESSION_BAR_COUNTS_15M = {
    "asia":   28,   # 7h * 4 bars/h
    "london": 24,   # 6h * 4 bars/h
    "ny":     32,   # 8h * 4 bars/h
}


def session_clock(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-bar session classification and running session extremes.

    Args:
        df: DataFrame with 'high', 'low' columns and a UTC DatetimeIndex
            (or a 'time' / 'timestamp' column convertible to UTC).

    Returns:
        DataFrame indexed identically to df with the columns described above.
    """
    _orig_idx = df.index

    if isinstance(df.index, pd.DatetimeIndex):
        ts = df.index
    elif "time" in df.columns:
        ts = pd.DatetimeIndex(pd.to_datetime(df["time"], utc=True))
    elif "timestamp" in df.columns:
        ts = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    else:
        raise ValueError(
            "session_clock requires a DatetimeIndex or 'time'/'timestamp' column"
        )

    if ts.tz is None:
        ts = ts.tz_localize("UTC")

    high = df["high"].astype(float)
    low = df["low"].astype(float)

    hours = pd.Series(ts.hour, index=df.index)

    # Vectorized session_id classification by UTC hour
    session_id = pd.Series(["none"] * len(df), index=df.index, dtype=object)
    for sid, (start, end) in SESSION_BOUNDARIES.items():
        mask = (hours >= start) & (hours < end)
        session_id.loc[mask] = sid

    # session_seq: increments at each session_id transition
    session_seq = (session_id != session_id.shift(1)).cumsum().astype(int)

    # session_bar_idx: 0-indexed within session_seq
    session_bar_idx = session_seq.groupby(session_seq).cumcount()

    # session_pct_elapsed: NaN for dead zone, else bar_idx / expected_count
    expected_count = session_id.map(SESSION_BAR_COUNTS_15M)
    session_pct_elapsed = (
        session_bar_idx.astype(float) / expected_count
    ).where(session_id != "none")

    # day_of_week
    day_of_week = pd.Series(ts.dayofweek, index=df.index, dtype=int)

    # Running extremes per session_seq (strict no-lookahead via cummax/cummin)
    session_high_running = high.groupby(session_seq).cummax()
    session_low_running = low.groupby(session_seq).cummin()

    result = pd.DataFrame(
        {
            "session_id": session_id,
            "session_seq": session_seq.astype(int),
            "session_bar_idx": session_bar_idx.astype(int),
            "session_pct_elapsed": session_pct_elapsed,
            "day_of_week": day_of_week,
            "session_high_running": session_high_running,
            "session_low_running": session_low_running,
        },
        index=df.index,
    )
    result.index = _orig_idx

    if (result["session_id"] == "none").all():
        raise RuntimeError(
            "session_clock invariant violation: no real-session bars detected"
        )

    return result
