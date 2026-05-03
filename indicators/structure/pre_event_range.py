"""
pre_event_range.py — Pre-event compression box anchored to scheduled events.

For each qualifying scheduled event in the live RESEARCH-layer news
calendar, computes the high/low of the N bars immediately preceding
event_dt and broadcasts those values onto every bar within the event's
[event_dt - pre_min, event_dt + post_min] window. Bars outside any
event window receive NaN box values and armed_event_id == 0.

This is the structural primitive that lets a strategy enter only on
breakouts of a pre-event compression range — Architecture A1 from the
NEWSBRK discovery report (event-overlap breakout, not post-event trend).

Consumes news_event_window for event-membership, then computes the
pre-event box once per event using the bars where time < event_dt.

Output columns (added to df, original index preserved):
    pre_event_high      : float          — max(high) of the box_bars bars
                                            before event_dt (NaN outside windows
                                            or if insufficient pre-event bars).
    pre_event_low       : float          — min(low) of those bars (NaN otherwise).
    armed_event_id      : int64          — same as news_event_id when bar is
                                            inside an armed event window with a
                                            valid box; 0 otherwise.
    pre_event_event_dt  : datetime64     — anchor event timestamp (NaT outside
                                            armed windows).

Lookahead safety:
    The box is computed exclusively from bars STRICTLY BEFORE event_dt.
    No bar at or after event_dt contributes to the box for that event.
    Strategies that use this indicator can safely test
    breakout-above-pre_event_high or breakdown-below-pre_event_low
    on event-window bars without forward bias.

Window boundary convention:
    Bars whose timestamp is in [event_dt - pre_min, event_dt + post_min)
    are considered armed (left-inclusive, right-exclusive). A bar at
    exactly event_dt + post_min is OUTSIDE the window. This matches
    news_event_window.py and the report-layer overlap convention so
    both indicators attribute boundary bars identically.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from indicators.macro.news_event_window import (
    _DEFAULT_CALENDAR_DIR,
    _ensure_utc_index,
    _load_events,
)

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "pre_event_range"
PIVOT_SOURCE = "none"


def pre_event_range(
    df: pd.DataFrame,
    *,
    box_bars: int = 6,
    currencies: list[str] | None = None,
    impact_filter: str | None = "High",
    pre_min: int = 15,
    post_min: int = 15,
    calendar_dir: Path | None = None,
) -> pd.DataFrame:
    """Add pre-event compression-box columns to *df*.

    Args:
        df: input DataFrame with 'high', 'low' columns and either a
            'time' column or DatetimeIndex.
        box_bars: number of bars immediately preceding event_dt that
                  define the compression box (default 6).
        currencies: ISO-3 currency codes to admit (None = all).
        impact_filter: single-impact filter (default 'High').
        pre_min: pre-event window minutes (default 15).
        post_min: post-event window minutes (default 15).
        calendar_dir: override RESEARCH calendar path (None = default).

    Returns:
        df (modified in place) with four new columns.
    """
    required = {"high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"pre_event_range: missing required columns {sorted(missing)}"
        )

    cal_dir = Path(calendar_dir) if calendar_dir is not None else _DEFAULT_CALENDAR_DIR
    ccy_tuple = tuple(sorted(set(currencies))) if currencies else None
    events = _load_events(cal_dir, impact_filter, ccy_tuple)

    n = len(df)
    df["pre_event_high"] = np.nan
    df["pre_event_low"] = np.nan
    df["armed_event_id"] = 0
    df["pre_event_event_dt"] = pd.NaT

    if n == 0 or len(events) == 0 or box_bars <= 0:
        return df

    bar_idx = _ensure_utc_index(df)
    bar_arr = bar_idx.asi8

    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)

    ev_dt_aware = pd.DatetimeIndex(events["datetime_utc"]).tz_localize("UTC")
    ev_dt_arr = ev_dt_aware.asi8
    ev_start_arr = (ev_dt_aware - pd.Timedelta(minutes=pre_min)).asi8
    ev_end_arr = (ev_dt_aware + pd.Timedelta(minutes=post_min)).asi8
    ev_id_arr = np.arange(1, len(events) + 1, dtype=np.int64)

    # Sort events by event_dt for deterministic processing.
    order = np.argsort(ev_dt_arr, kind="mergesort")
    ev_dt_sorted = ev_dt_arr[order]
    ev_start_sorted = ev_start_arr[order]
    ev_end_sorted = ev_end_arr[order]
    ev_id_sorted = ev_id_arr[order]

    out_high = np.full(n, np.nan)
    out_low = np.full(n, np.nan)
    out_id = np.zeros(n, dtype=np.int64)
    out_dt = np.full(n, pd.NaT.value, dtype=np.int64)

    # For each event, find the box and broadcast.
    for k in range(len(ev_dt_sorted)):
        ev_dt_k = ev_dt_sorted[k]
        ev_start_k = ev_start_sorted[k]
        ev_end_k = ev_end_sorted[k]
        ev_id_k = ev_id_sorted[k]

        # Box: bars strictly before event_dt — find the last box_bars
        # bars where time < event_dt.
        pre_idx = np.searchsorted(bar_arr, ev_dt_k, side="left")
        if pre_idx < box_bars:
            # Insufficient pre-event bars to form the box — skip event.
            continue
        box_start = pre_idx - box_bars
        box_high = float(high_arr[box_start:pre_idx].max())
        box_low = float(low_arr[box_start:pre_idx].min())

        # Window: bars whose time falls in [event_start, event_end).
        # Boundary convention deliberately matches news_event_window:
        #   side='left' on event_start  → bars >= ev_start are included
        #   side='left' on event_end    → bars >= ev_end are excluded
        # i.e. bar at exactly ev_end is OUTSIDE.
        win_lo = np.searchsorted(bar_arr, ev_start_k, side="left")
        win_hi = np.searchsorted(bar_arr, ev_end_k, side="left")
        if win_lo >= win_hi:
            continue

        # Broadcast box to window bars. Earliest event wins on overlap
        # (matches news_event_window's first-fire rule).
        for i in range(win_lo, win_hi):
            if out_id[i] == 0:
                out_high[i] = box_high
                out_low[i] = box_low
                out_id[i] = ev_id_k
                out_dt[i] = ev_dt_k

    df["pre_event_high"] = out_high
    df["pre_event_low"] = out_low
    df["armed_event_id"] = out_id
    df["pre_event_event_dt"] = pd.to_datetime(out_dt, utc=True)

    return df
