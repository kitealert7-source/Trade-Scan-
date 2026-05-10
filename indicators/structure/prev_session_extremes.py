"""
Prior-Session Extremes — Immediately-Prior Real Session High/Low + Armed-State

For each bar, emit:

  prev_session_high / prev_session_low / prev_session_id
    The high and low of the most recently COMPLETED real session (asia, london,
    or ny — never the dead zone). Marks become available at the FIRST BAR AFTER
    the real session ends and forward-fill until the next real session ends.

    Default behaviour (`expand_during_dead_zone=False`): dead-zone bars never
    set new prev_session marks — Asia at 00:00 UTC continues to reference the
    prior-day NY's high/low, not anything accumulated during 21-00 UTC.

    Optional Pine-parity behaviour (`expand_during_dead_zone=True`): during
    dead-zone bars, prev_session_high is expanded UPWARD by the dead-zone
    bar's high if higher, and prev_session_low expanded DOWNWARD by the
    dead-zone bar's low if lower. Asia at 00:00 inherits the union of the
    prior NY session's extremes and any dead-zone breach. Matches Pine v5
    PriorSessionBreakout strategy semantics.

  armed_long / armed_short
    Per-bar boolean breakout-eligibility flag implementing the "gap-open vs
    inside-open" rule the strategy gates on:

      Rule 1 (inside open). If the FIRST bar of the current real session has
        OPEN that is at-or-inside the prev-extreme reference (long: open <=
        prev_session_high; short: open >= prev_session_low), the session is
        armed from bar 1. The first close-break is eligible immediately —
        no extra "prior bar inside" requirement.

      Rule 2 (gap open). If the first bar's OPEN is already past the
        prev-extreme reference (long: open > prev_session_high; short:
        open < prev_session_low), the session is in gap-open state and the
        armed flag stays False until at least one subsequent bar in the
        same session closes back inside the reference (re-arm event). Once
        re-armed, all subsequent close-breaks are eligible.

    armed_* is False during the dead zone (session_id == 'none') by definition.

Strict no-lookahead at every step:
  - prev_session marks are frozen at the first bar AFTER session end
    (sess_high.shift(1) at the boundary)
  - re-arm count uses cumsum_within_session - current_bar_contribution, so the
    current bar never contributes to its own re-arm
  - "session opened inside" is determined from the FIRST bar's open + prev_high
    (both available at that first bar) — never reaches into the future

Output columns:
    prev_session_high : float
    prev_session_low  : float
    prev_session_id   : str
    armed_long        : bool
    armed_short       : bool
"""

import pandas as pd
import numpy as np

# --- Semantic Contract ---
SIGNAL_PRIMITIVE = "prev_session_extremes"
PIVOT_SOURCE = "session_high_low"

REAL_SESSIONS = ("asia", "london", "ny")


def prev_session_extremes(
    sc: pd.DataFrame,
    df: pd.DataFrame,
    expand_during_dead_zone: bool = False,
) -> pd.DataFrame:
    """
    Args:
        sc: session_clock output DataFrame with 'session_id', 'session_seq',
            'session_high_running', 'session_low_running' columns.
        df: original OHLC DataFrame (must contain 'open', 'close', 'high',
            'low' columns when expand_during_dead_zone=True; otherwise only
            'open' and 'close').
        expand_during_dead_zone: if True, dead-zone bars expand the frozen
            prev_session_high upward and prev_session_low downward when their
            high/low breaches the reference. The expanded value persists into
            the next real session. Default False (preserves the original
            no-expansion semantics for backward compatibility with S01/S02
            PSBRK lineages).

    Returns:
        DataFrame indexed identically with prev_session_high, prev_session_low,
        prev_session_id, armed_long, armed_short.
    """
    required_sc = {
        "session_id",
        "session_seq",
        "session_high_running",
        "session_low_running",
    }
    missing_sc = required_sc - set(sc.columns)
    if missing_sc:
        raise ValueError(
            f"prev_session_extremes requires columns {missing_sc} from session_clock"
        )
    required_df = {"open", "close"}
    if expand_during_dead_zone:
        required_df = required_df | {"high", "low"}
    missing_df = required_df - set(df.columns)
    if missing_df:
        raise ValueError(
            f"prev_session_extremes requires {missing_df} columns in df"
        )

    sess_id = sc["session_id"]
    sess_seq = sc["session_seq"]
    sess_high = sc["session_high_running"]
    sess_low = sc["session_low_running"]
    open_px = df["open"].astype(float)
    close = df["close"].astype(float)

    # --- Prev-session marks (frozen at session end, ffilled forward) ---
    seq_change = sess_seq != sess_seq.shift(1)
    prev_was_real = sess_id.shift(1).isin(REAL_SESSIONS)
    eors = seq_change & prev_was_real  # end-of-real-session boundary

    prev_high = pd.Series(np.nan, index=sc.index, dtype=float)
    prev_low = pd.Series(np.nan, index=sc.index, dtype=float)
    prev_id = pd.Series([np.nan] * len(sc), index=sc.index, dtype=object)

    prev_high.loc[eors] = sess_high.shift(1).loc[eors]
    prev_low.loc[eors] = sess_low.shift(1).loc[eors]
    prev_id.loc[eors] = sess_id.shift(1).loc[eors]

    prev_high = prev_high.ffill()
    prev_low = prev_low.ffill()
    prev_id = prev_id.ffill()

    # --- Optional dead-zone expansion (Pine-parity) ---
    # Within each ffill segment (one segment = bars sharing the same forward-
    # filled prev_high/low value), accumulate the cummax/cummin of dead-zone
    # bars' high/low. The cummax must then be forward-filled within the same
    # segment to propagate the bumped value across subsequent real-session
    # bars (Pine's `var prev_sess_hi` persists across all bars until the next
    # real session ends). Element-wise combine with the base ffilled value:
    # the bar's prev_high becomes max(base, dead_zone_running_max).
    #
    # Note: pandas groupby().cummax() preserves NaN at NaN positions instead
    # of skipping them, so an explicit per-group ffill is required after the
    # cummax to carry the running max into Asia/london bars.
    if expand_during_dead_zone:
        seg_id = eors.cumsum()
        is_dead = sess_id == "none"
        dead_high_only = df["high"].astype(float).where(is_dead)
        dead_low_only = df["low"].astype(float).where(is_dead)
        expanded_high_in_seg = (
            dead_high_only.groupby(seg_id).cummax().groupby(seg_id).ffill()
        )
        expanded_low_in_seg = (
            dead_low_only.groupby(seg_id).cummin().groupby(seg_id).ffill()
        )
        # element-wise combine — skipna=True so NaN values are ignored
        prev_high = pd.concat([prev_high, expanded_high_in_seg], axis=1).max(
            axis=1, skipna=True
        )
        prev_low = pd.concat([prev_low, expanded_low_in_seg], axis=1).min(
            axis=1, skipna=True
        )

    # --- Rule 1: Did the session OPEN inside the reference? ---
    # transform('first') broadcasts the first-bar value of each session_seq
    # back across all bars in that session.
    open_at_first = open_px.groupby(sess_seq).transform("first")
    prev_high_at_first = prev_high.groupby(sess_seq).transform("first")
    prev_low_at_first = prev_low.groupby(sess_seq).transform("first")
    session_opened_inside_long = (open_at_first <= prev_high_at_first).fillna(False)
    session_opened_inside_short = (open_at_first >= prev_low_at_first).fillna(False)

    # --- Rule 2: Re-arm via prior in-session close (for gap-open sessions) ---
    below_ref_long = (close <= prev_high).fillna(False)
    above_ref_short = (close >= prev_low).fillna(False)
    below_int = below_ref_long.astype(int)
    above_int = above_ref_short.astype(int)

    # cumsum_within_seq - current_bar_contribution = "prior count, exclusive of self"
    cum_below_in_seq = below_int.groupby(sess_seq).cumsum()
    cum_above_in_seq = above_int.groupby(sess_seq).cumsum()
    prior_below = cum_below_in_seq - below_int
    prior_above = cum_above_in_seq - above_int
    re_armed_long = prior_below > 0
    re_armed_short = prior_above > 0

    # --- Combined armed flags (Rule 1 OR Rule 2), gated on real session ---
    real = sess_id.isin(REAL_SESSIONS)
    armed_long = (session_opened_inside_long | re_armed_long) & real
    armed_short = (session_opened_inside_short | re_armed_short) & real

    return pd.DataFrame(
        {
            "prev_session_high": prev_high,
            "prev_session_low": prev_low,
            "prev_session_id": prev_id,
            "armed_long": armed_long,
            "armed_short": armed_short,
        },
        index=sc.index,
    )
