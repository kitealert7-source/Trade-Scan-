"""
Session Clock — XAUUSD Liquidity-Driven Session Boundaries

Per-bar session classification, sequence numbering, running extremes, timing,
and day-of-week. Strict no-lookahead (running extremes via cummax/cummin per
session_seq).

Boundaries (UTC) — ALIGNED TO THE CANONICAL REPORT/RESEARCH SESSION DEFINITION
(`tools/report/report_sessions.py` _classify_session, mirrored from stage2_compiler.py),
so strategy SESSION GATING uses the exact same hours that report bucketing / the AK
report Session Breakdown use. These three MUST stay in sync — see SESSION_BOUNDARIES
note below. (Prior XAU-liquidity-tuned values asia 0-7 / london 7-13 / ny 13-21 were
unused by any strategy and diverged from the report basis; realigned 2026-06-23.)
    asia:   00:00 - 08:00
    london: 08:00 - 16:00   (matches report_sessions._LONDON_START/_END = 8, 16)
    ny:     16:00 - 24:00

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

# --- Canonical Report/Research Session Boundaries (UTC hours) ---
# MUST mirror tools/report/report_sessions.py (_ASIA/_LONDON/_NY _START/_END) and
# stage2_compiler.py. Gating-vs-reporting consistency depends on it. NY covers 16-24
# (no dead zone) to match the report's _NY_END = 24. (Single-source-of-truth refactor
# — import these from one shared module — is a deferred follow-up.)
SESSION_BOUNDARIES = {
    "asia":   (0, 8),
    "london": (8, 16),
    "ny":     (16, 24),
}

# Expected 15M-bar count per session (drives pct_elapsed only; gating uses session_id)
SESSION_BAR_COUNTS_15M = {
    "asia":   32,   # 8h * 4 bars/h
    "london": 32,   # 8h * 4 bars/h
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
