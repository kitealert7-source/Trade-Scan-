"""
news_event_window.py — Per-bar economic-event window state indicator.

Reads the live RESEARCH-layer news calendar at
data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/ and computes per-bar
membership in [event_dt - pre_min, event_dt + post_min] windows for
events matching the requested currency / impact filter.

Single source of truth for news-window state — strategies and other
indicators (e.g. pre_event_range) consume this output rather than
re-reading the calendar themselves.

External dependency:
    data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/NEWS_CALENDAR_*_RESEARCH.csv
    Schema: datetime_utc, currency, impact, event[, source]

Output columns (added to df, original index preserved):
    news_in_window  : bool          — bar overlaps any qualifying event window
    news_in_pre     : bool          — bar is in [event - pre_min, event)
    news_in_post    : bool          — bar is in [event, event + post_min]
    news_event_id   : int64         — incremental id of matched event (0 = none)
    news_event_dt   : datetime64    — timestamp of matched event (NaT = none)
    news_impact     : str           — impact tag of matched event ('' = none)
    news_currency   : str           — currency tag of matched event ('' = none)

Multi-event tie-breaker:
    A bar that overlaps multiple event windows is attributed to the
    event with the EARLIEST window_start (first-fire rule). The boolean
    in_window / in_pre / in_post flags are still independent — a bar
    inside two events' pre regions reads in_pre=True for both
    (only the id/dt/impact/currency columns are single-attribution).

Lookahead safety:
    Calendar timestamps are scheduled events known in advance; using
    them at signal time does not introduce look-ahead. The indicator
    flags the bar at time t based on whether t falls inside a window
    centered on a scheduled event — not on the post-release outcome.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "news_event_window"
PIVOT_SOURCE = "none"


# =============================================================================
# GOVERNANCE: External Dependency Isolation
# =============================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_CALENDAR_DIR = (
    _PROJECT_ROOT / "data_root" / "EXTERNAL_DATA"
    / "NEWS_CALENDAR" / "RESEARCH"
)


# Per-process cache: avoid re-parsing the calendar for repeated calls
# with identical (calendar_dir, impact_filter, currencies) keys.
_EVENT_CACHE: dict = {}


def _load_events(
    calendar_dir: Path,
    impact_filter: str | None,
    currencies: tuple[str, ...] | None,
) -> pd.DataFrame:
    """Load + filter calendar events. Returns DataFrame sorted by datetime_utc.

    Columns: datetime_utc (UTC-naive), currency, impact, event.
    """
    cache_key = (str(calendar_dir), impact_filter, currencies)
    cached = _EVENT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if not calendar_dir.exists() or not calendar_dir.is_dir():
        empty = pd.DataFrame(
            columns=["datetime_utc", "currency", "impact", "event"]
        )
        _EVENT_CACHE[cache_key] = empty
        return empty

    csv_files = sorted(calendar_dir.glob("*.csv"))
    if not csv_files:
        empty = pd.DataFrame(
            columns=["datetime_utc", "currency", "impact", "event"]
        )
        _EVENT_CACHE[cache_key] = empty
        return empty

    frames = []
    for f in csv_files:
        chunk = pd.read_csv(f, encoding="utf-8")
        if len(chunk) == 0:
            continue
        chunk["datetime_utc"] = pd.to_datetime(chunk["datetime_utc"])
        frames.append(chunk)

    if not frames:
        empty = pd.DataFrame(
            columns=["datetime_utc", "currency", "impact", "event"]
        )
        _EVENT_CACHE[cache_key] = empty
        return empty

    events = pd.concat(frames, ignore_index=True)

    # Calendar is RESEARCH-layer: must be UTC-naive. Mirror loader assertion.
    if events["datetime_utc"].dt.tz is not None:
        raise AssertionError(
            "news_event_window: RESEARCH datetime_utc must be UTC-naive — "
            "calendar is double-normalized or corrupt."
        )

    events["currency"] = events["currency"].astype(str).str.strip().str.upper()
    events["impact"] = events["impact"].astype(str).str.strip().str.capitalize()
    if "event" not in events.columns:
        events["event"] = "Unknown"

    if impact_filter:
        events = events[events["impact"] == impact_filter]
    if currencies:
        events = events[events["currency"].isin(currencies)]

    events = events.drop_duplicates(
        subset=["datetime_utc", "currency", "event"], keep="first"
    )
    events = events.sort_values("datetime_utc").reset_index(drop=True)
    events = events[["datetime_utc", "currency", "impact", "event"]]

    _EVENT_CACHE[cache_key] = events
    return events


def _ensure_utc_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Return a UTC-aware DatetimeIndex aligned to df rows.

    Accepts df with either a 'time' column or a DatetimeIndex.
    """
    if "time" in df.columns:
        ts = pd.to_datetime(df["time"], errors="coerce", utc=True)
        return pd.DatetimeIndex(ts)
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        return idx
    raise ValueError(
        "news_event_window: df must have a 'time' column or a DatetimeIndex"
    )


def news_event_window(
    df: pd.DataFrame,
    *,
    currencies: list[str] | None = None,
    impact_filter: str | None = "High",
    pre_min: int = 15,
    post_min: int = 15,
    calendar_dir: Path | None = None,
) -> pd.DataFrame:
    """Add per-bar news event-window columns to *df*.

    Args:
        df: input DataFrame with a 'time' column or DatetimeIndex.
        currencies: list of ISO-3 currency codes to admit (None = all).
        impact_filter: single-impact filter ('High', 'Medium', 'Low').
                       None = all impacts.
        pre_min: minutes before event_dt admitted as pre-window.
        post_min: minutes after event_dt admitted as post-window.
        calendar_dir: override RESEARCH calendar path (None = default).

    Returns:
        df (modified in place) with seven new columns. Original index
        and row order are preserved.
    """
    cal_dir = Path(calendar_dir) if calendar_dir is not None else _DEFAULT_CALENDAR_DIR
    ccy_tuple = tuple(sorted(set(currencies))) if currencies else None
    events = _load_events(cal_dir, impact_filter, ccy_tuple)

    n = len(df)

    # Pre-allocate output columns with sensible defaults.
    df["news_in_window"] = False
    df["news_in_pre"] = False
    df["news_in_post"] = False
    df["news_event_id"] = 0
    df["news_event_dt"] = pd.NaT
    df["news_impact"] = ""
    df["news_currency"] = ""

    if n == 0 or len(events) == 0:
        return df

    bar_idx = _ensure_utc_index(df)

    # Convert events to UTC-aware for comparison.
    ev_dt = pd.DatetimeIndex(events["datetime_utc"]).tz_localize("UTC")
    ev_start = ev_dt - pd.Timedelta(minutes=pre_min)
    ev_end = ev_dt + pd.Timedelta(minutes=post_min)
    ev_id_arr = np.arange(1, len(events) + 1, dtype=np.int64)
    ev_impact = events["impact"].astype(str).to_numpy()
    ev_ccy = events["currency"].astype(str).to_numpy()

    bar_arr = bar_idx.asi8
    ev_start_arr = ev_start.asi8
    ev_end_arr = ev_end.asi8
    ev_dt_arr = ev_dt.asi8

    # Sort events by start; with a fixed (pre_min, post_min) for all events
    # the end array is then also monotonically increasing. This allows a
    # fully vectorized two-searchsorted lookup below — O((n + m) log m)
    # total instead of the per-bar O(events) forward scan an earlier
    # implementation used. If we ever introduce per-event window sizing
    # (e.g. impact-tiered pre/post minutes), this monotonicity assumption
    # breaks and the lookup must be revisited.
    order = np.argsort(ev_start_arr, kind="mergesort")
    ev_start_sorted = ev_start_arr[order]
    ev_end_sorted = ev_end_arr[order]
    ev_dt_sorted = ev_dt_arr[order]
    ev_id_sorted = ev_id_arr[order]
    ev_impact_sorted = ev_impact[order]
    ev_ccy_sorted = ev_ccy[order]

    # Boundary convention: a bar at time bt matches event j iff
    #     ev_start_sorted[j] <= bt < ev_end_sorted[j]
    # i.e. left-inclusive, right-exclusive [start, end). This matches
    # pre_event_range.py and the report-layer overlap semantics.
    #
    # `insertion` = first index where ev_start > bt → events with start <= bt
    #   are at [0, insertion).
    # `lo`        = first index where ev_end > bt   → events with end > bt
    #   are at [lo, m).
    # Their intersection is [lo, insertion). When non-empty, the smallest
    # index `lo` is the earliest-starting event whose window contains bt
    # (first-fire tie-breaker, identical to the prior implementation
    # because event ends are monotonic when starts are).
    insertion = np.searchsorted(ev_start_sorted, bar_arr, side="right")
    lo = np.searchsorted(ev_end_sorted, bar_arr, side="right")
    matched = lo < insertion

    out_in_window = matched
    out_event_id = np.where(matched, ev_id_sorted[np.clip(lo, 0, len(ev_id_sorted) - 1)], 0).astype(np.int64)
    out_event_dt_raw = np.where(
        matched,
        ev_dt_sorted[np.clip(lo, 0, len(ev_dt_sorted) - 1)],
        pd.NaT.value,
    ).astype(np.int64)

    # bt < event_dt → in pre region; bt >= event_dt → in post region.
    matched_event_dt = ev_dt_sorted[np.clip(lo, 0, len(ev_dt_sorted) - 1)]
    out_in_pre = matched & (bar_arr < matched_event_dt)
    out_in_post = matched & (bar_arr >= matched_event_dt)

    # Object arrays cannot be vectorized with np.where in older numpy;
    # build via boolean indexing.
    out_impact = np.full(n, "", dtype=object)
    out_currency = np.full(n, "", dtype=object)
    if matched.any():
        idx_matched = np.where(matched)[0]
        sel = lo[matched]
        out_impact[idx_matched] = ev_impact_sorted[sel]
        out_currency[idx_matched] = ev_ccy_sorted[sel]

    df["news_in_window"] = out_in_window
    df["news_in_pre"] = out_in_pre
    df["news_in_post"] = out_in_post
    df["news_event_id"] = out_event_id
    df["news_event_dt"] = pd.to_datetime(out_event_dt_raw, utc=True)
    df["news_impact"] = out_impact
    df["news_currency"] = out_currency

    return df
