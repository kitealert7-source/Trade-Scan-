"""
Fair Value Gap (FVG) — 3-bar Price Imbalance Detector

Detects bullish and bearish Fair Value Gaps (price imbalances) on a 3-bar
window, tracks active zones with first-touch and full-invalidation events,
and exposes the most-recent active zone bounds per bar.

A bullish FVG forms on bar i when low[i] > high[i-2] — an unfilled gap
sits between bar[i-2]'s high and bar[i]'s low. ICT/SMC literature treats
this as institutional-flow displacement: price moved too fast for normal
counter-flow to fill the zone, so subsequent retracements into the zone
tend to produce reactions.

Bullish FVG zone:    [bottom = high[i-2], top = low[i]]
Bearish FVG zone:    [bottom = high[i],   top = low[i-2]]

Two touch rules are emitted as separate columns so a strategy can A/B
test them without recomputing the indicator:
    CLOSE rule (more conservative): close penetrates the zone
        bull: close[i] <= top      bear: close[i] >= bottom
    WICK rule  (more sensitive):    wick penetrates the zone
        bull: low[i]   <= top      bear: high[i]  >= bottom

Note: WICK-rule touch is a strict superset of CLOSE-rule touch — if close
penetrated then the wick must have also (low <= close <= top). They can
fire on the same bar.

Required input columns:
    ['high', 'low', 'close']

Output columns:
    fvg_bull_formed                — int {0,1}: bull FVG created on this bar
    fvg_bear_formed                — int {0,1}: bear FVG created on this bar
    fvg_bull_first_touch_close     — int {0,1}: first close-rule touch of an
                                                 active bull FVG
    fvg_bull_first_touch_wick      — int {0,1}: first wick-rule touch
    fvg_bear_first_touch_close     — int {0,1}: bear mirror, close-rule
    fvg_bear_first_touch_wick      — int {0,1}: bear mirror, wick-rule
    fvg_bull_invalidated           — int {0,1}: bull FVG invalidated
                                                 (close < bottom)
    fvg_bear_invalidated           — int {0,1}: bear FVG invalidated
                                                 (close > top)
    fvg_bull_top_active            — float: top of most-recent active bull FVG
                                            (NaN if none active)
    fvg_bull_bottom_active         — float: bottom of most-recent active bull FVG
    fvg_bear_top_active            — float: top of most-recent active bear FVG
    fvg_bear_bottom_active         — float: bottom of most-recent active bear FVG

Touch-vs-invalidation semantics:
    If a zone is invalidated on bar i (close past the far side), no touch
    event fires on that bar — the zone is dead at bar close, so emitting a
    touch would create an entry signal that is already stopped out.

Bar-alignment / fill contract:
    Detection on bar i uses [i-2, i-1, i]. Touch/invalidation checks for a
    zone formed on bar i begin on bar i+1 (no same-bar mitigation). Signal
    fires at bar i close; fill at bar i+1 open per the engine's
    signal_bar_idx == fill_bar_idx - 1 contract. No lookahead.
"""

import numpy as np
import pandas as pd

# TD-003: semantic-contract metadata. FVG is a 3-bar window structure
# detector that publishes zone bounds + touch / invalidation events.
SIGNAL_PRIMITIVE = "three_bar_imbalance_zone"

_DEFAULT_MAX_ACTIVE = 10


def compute_fair_value_gap(
    df: pd.DataFrame,
    max_active: int = _DEFAULT_MAX_ACTIVE,
) -> pd.DataFrame:
    """Compute Fair Value Gap zones, events, and active-zone bounds."""
    n = len(df)
    high = df['high'].to_numpy(dtype=float)
    low = df['low'].to_numpy(dtype=float)
    close = df['close'].to_numpy(dtype=float)

    fvg_bull_formed = np.zeros(n, dtype=int)
    fvg_bear_formed = np.zeros(n, dtype=int)
    fvg_bull_first_touch_close = np.zeros(n, dtype=int)
    fvg_bull_first_touch_wick = np.zeros(n, dtype=int)
    fvg_bear_first_touch_close = np.zeros(n, dtype=int)
    fvg_bear_first_touch_wick = np.zeros(n, dtype=int)
    fvg_bull_invalidated = np.zeros(n, dtype=int)
    fvg_bear_invalidated = np.zeros(n, dtype=int)
    fvg_bull_top_active = np.full(n, np.nan, dtype=float)
    fvg_bull_bottom_active = np.full(n, np.nan, dtype=float)
    fvg_bear_top_active = np.full(n, np.nan, dtype=float)
    fvg_bear_bottom_active = np.full(n, np.nan, dtype=float)

    # Per-zone state: [top, bottom, touched_close, touched_wick]
    bull_zones: list[list] = []
    bear_zones: list[list] = []

    for i in range(2, n):
        kept_bulls = []
        any_close_touch = False
        any_wick_touch = False
        any_invalid = False
        for top, bottom, t_close, t_wick in bull_zones:
            if close[i] < bottom:
                any_invalid = True
                continue
            if not t_wick and low[i] <= top:
                t_wick = True
                any_wick_touch = True
            if not t_close and close[i] <= top:
                t_close = True
                any_close_touch = True
            kept_bulls.append([top, bottom, t_close, t_wick])
        bull_zones = kept_bulls
        if any_close_touch:
            fvg_bull_first_touch_close[i] = 1
        if any_wick_touch:
            fvg_bull_first_touch_wick[i] = 1
        if any_invalid:
            fvg_bull_invalidated[i] = 1

        kept_bears = []
        any_close_touch_b = False
        any_wick_touch_b = False
        any_invalid_b = False
        for top, bottom, t_close, t_wick in bear_zones:
            if close[i] > top:
                any_invalid_b = True
                continue
            if not t_wick and high[i] >= bottom:
                t_wick = True
                any_wick_touch_b = True
            if not t_close and close[i] >= bottom:
                t_close = True
                any_close_touch_b = True
            kept_bears.append([top, bottom, t_close, t_wick])
        bear_zones = kept_bears
        if any_close_touch_b:
            fvg_bear_first_touch_close[i] = 1
        if any_wick_touch_b:
            fvg_bear_first_touch_wick[i] = 1
        if any_invalid_b:
            fvg_bear_invalidated[i] = 1

        if low[i] > high[i - 2]:
            bull_zones.append([low[i], high[i - 2], False, False])
            fvg_bull_formed[i] = 1
            if len(bull_zones) > max_active:
                bull_zones.pop(0)

        if high[i] < low[i - 2]:
            bear_zones.append([low[i - 2], high[i], False, False])
            fvg_bear_formed[i] = 1
            if len(bear_zones) > max_active:
                bear_zones.pop(0)

        if bull_zones:
            top, bottom, _, _ = bull_zones[-1]
            fvg_bull_top_active[i] = top
            fvg_bull_bottom_active[i] = bottom
        if bear_zones:
            top, bottom, _, _ = bear_zones[-1]
            fvg_bear_top_active[i] = top
            fvg_bear_bottom_active[i] = bottom

    df['fvg_bull_formed'] = fvg_bull_formed
    df['fvg_bear_formed'] = fvg_bear_formed
    df['fvg_bull_first_touch_close'] = fvg_bull_first_touch_close
    df['fvg_bull_first_touch_wick'] = fvg_bull_first_touch_wick
    df['fvg_bear_first_touch_close'] = fvg_bear_first_touch_close
    df['fvg_bear_first_touch_wick'] = fvg_bear_first_touch_wick
    df['fvg_bull_invalidated'] = fvg_bull_invalidated
    df['fvg_bear_invalidated'] = fvg_bear_invalidated
    df['fvg_bull_top_active'] = fvg_bull_top_active
    df['fvg_bull_bottom_active'] = fvg_bull_bottom_active
    df['fvg_bear_top_active'] = fvg_bear_top_active
    df['fvg_bear_bottom_active'] = fvg_bear_bottom_active
    return df


fair_value_gap = compute_fair_value_gap
