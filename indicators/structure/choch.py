"""
Change of Character (CHOCH) — Structural Signal Module

Detects and tracks CHOCH events: the first bar that closes beyond a mature
swing level, signalling structural failure of the prior trend.

Features:
- Fully extracted from strategy logic — no trading code
- Loop-based streak computation (required for cumulative state)
- Two-stage API: event detection then persistence layering
- Deterministic, no randomness

Required input columns:
    ['high', 'low', 'close']
Index:
    pandas DatetimeIndex (UTC-normalised or timezone-aware)

Parameters (fixed — match strategy 26_STR_XAUUSD_1H_CHOCH_S01_V1_P00):
    SWING_LOOKBACK  = 20  bars
    MIN_SWING_AGE   = 3   bars
    MIN_SWINGS      = 3   consecutive swings required for trend maturity
"""

import numpy as np
import pandas as pd

from indicators.structure.highest_high import highest_high
from indicators.structure.lowest_low import lowest_low

# ---------------------------------------------------------------------------
# Fixed parameters — must match source strategy; do not modify
# ---------------------------------------------------------------------------
_SWING_LOOKBACK = 20
_MIN_SWING_AGE  = 3
_MIN_SWINGS     = 3


# ---------------------------------------------------------------------------
# Stage 1 — Event detection
# ---------------------------------------------------------------------------

def compute_choch_state(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replicate prepare_indicators logic from strategy 26_STR_XAUUSD_1H_CHOCH_S01_V1_P00.

    Computes swing structure and emits discrete CHOCH events.

    Adds columns:
        swing_high      — rolling highest high (lookback=20, shifted by 3 bars)
        swing_low       — rolling lowest low  (lookback=20, shifted by 3 bars)
        lh_streak       — consecutive lower-highs (downtrend depth counter)
        hl_streak       — consecutive higher-lows (uptrend depth counter)
        choch_event     — +1 bullish CHOCH / -1 bearish CHOCH / 0 no event

    Args:
        df: DataFrame with ['high', 'low', 'close'] and DatetimeIndex.

    Returns:
        df with the above columns added in-place.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df.index = pd.DatetimeIndex(df['timestamp'])
        elif 'time' in df.columns:
            df.index = pd.DatetimeIndex(df['time'])

    # Swing levels — shifted by MIN_SWING_AGE to enforce minimum age
    df['swing_high'] = highest_high(df['high'], window=_SWING_LOOKBACK, shift=_MIN_SWING_AGE)
    df['swing_low']  = lowest_low(df['low'],    window=_SWING_LOOKBACK, shift=_MIN_SWING_AGE)

    sh = df['swing_high']
    sl = df['swing_low']

    # Bar-by-bar: lower-high and higher-low flags
    lower_high = (sh < sh.shift(1)).astype(int)
    higher_low = (sl > sl.shift(1)).astype(int)

    # Cumulative streak counters — loop required (state depends on prior state)
    lh_streak = lower_high.copy().astype(float)
    hl_streak = higher_low.copy().astype(float)

    for i in range(1, len(df)):
        lh_streak.iloc[i] = lh_streak.iloc[i - 1] + 1 if lower_high.iloc[i] else 0
        hl_streak.iloc[i] = hl_streak.iloc[i - 1] + 1 if higher_low.iloc[i] else 0

    df['lh_streak'] = lh_streak
    df['hl_streak'] = hl_streak

    # CHOCH event: structural break of a mature trend
    # Bullish  (+1): mature downtrend (3+ lower-highs), close breaks above swing_high
    # Bearish  (-1): mature uptrend  (3+ higher-lows),  close breaks below swing_low
    bullish = (df['lh_streak'] >= _MIN_SWINGS) & (df['close'] > df['swing_high'])
    bearish = (df['hl_streak'] >= _MIN_SWINGS) & (df['close'] < df['swing_low'])

    df['choch_event'] = np.where(bullish, 1, np.where(bearish, -1, 0)).astype(int)

    return df


# ---------------------------------------------------------------------------
# Stage 2 — Persistent state layer
# ---------------------------------------------------------------------------

def apply_choch_state(df: pd.DataFrame, persistence_bars: int = 15) -> pd.DataFrame:
    """
    Convert discrete CHOCH events into a persistent context window.

    Requires compute_choch_state() to have been run first (choch_event must exist).

    Adds columns:
        choch_active      — bool: True while within persistence window
        choch_direction   — int:  +1 / -1 / 0
        choch_bars_since  — int:  bars elapsed since last CHOCH event

    State rules:
        On choch_event != 0  → active=True, direction=event, bars_since=0
        Otherwise            → bars_since += 1
                               if bars_since > persistence_bars → active=False, direction=0

    Args:
        df:                DataFrame with 'choch_event' column.
        persistence_bars:  How many bars a CHOCH remains active after the event bar.

    Returns:
        df with the above columns added in-place.
    """
    if 'choch_event' not in df.columns:
        raise ValueError("compute_choch_state() must be called before apply_choch_state()")

    n = len(df)
    active     = np.zeros(n, dtype=bool)
    direction  = np.zeros(n, dtype=int)
    bars_since = np.full(n, -1, dtype=int)  # -1 = never triggered

    current_direction  = 0
    current_bars_since = -1  # -1 = never triggered

    for i in range(n):
        event = int(df['choch_event'].iloc[i])

        if event != 0:
            current_direction  = event
            current_bars_since = 0
        elif current_bars_since >= 0:
            # only increment once triggered; leave at -1 until first event
            current_bars_since += 1

        if 0 <= current_bars_since <= persistence_bars:
            active[i]    = True
            direction[i] = current_direction
        else:
            active[i]    = False
            direction[i] = 0

        bars_since[i] = current_bars_since

    df['choch_active']     = active
    df['choch_direction']  = direction
    df['choch_bars_since'] = bars_since

    return df
