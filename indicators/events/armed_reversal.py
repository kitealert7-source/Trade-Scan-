"""
Armed-Reversal Event Engine — generic extreme -> arm -> re-arm -> reversal primitive.

A reusable EVENT PRIMITIVE (not a strategy, not a price indicator): given generic boolean
condition series, it runs the universal "fade after an extreme" state machine and emits
entry events + arm metadata. It knows NOTHING about positions, stops, ATR, exits,
pyramiding, or trade management — those belong to strategy.py.

Pattern (short side; long mirrors):
    stretch_short fires                         -> ARM    (anchor = high, timer = window)
    new higher high AND stretch_short still True -> RE-ARM (update anchor, reset timer)  [no loss]
    bearish_reversal (opposite-colored close)   -> EMIT entry_short, back to FLAT
    `window` bars since the last extreme          -> DISARM (no entry, no loss), back to FLAT

Re-arm requires BOTH a new extreme AND the stretch still holding (per design) — a higher
high that is no longer beyond threshold does not re-anchor. The structural stop, ATR buffer,
regime gate, exits, and reentry are the STRATEGY's job; this engine just emits the events.

Reusable for any stretch family — DMA, RSI, IBS, Bollinger %B, z-score, CCI, SpikeFade —
by passing that family's own stretch/reversal booleans. The engine is condition-agnostic.

Inputs (all aligned to the same index):
    stretch_long / stretch_short   : bool Series — the extreme/arming condition, per side
    bullish_reversal / bearish_reversal : bool Series — the reversal (entry trigger), per side
    high, low                      : float Series — price extremes that define the anchor
    window                         : int — bars from the last extreme before disarm (default 3)
    strength                       : float Series | None — optional magnitude (e.g. |dma|, |z|)
                                     snapshotted at each extreme into arm_strength; None -> NaN

Outputs (DataFrame, same index):
    entry_long, entry_short  : bool  — pattern completed this bar (strategy decides whether to act)
    arm_high, arm_low        : float — running anchor extreme while armed / at the entry bar (else NaN)
    arm_strength             : float — `strength` at the current extreme (NaN if none / FLAT)
    bars_since_extreme       : int   — bars since the last extreme update (-1 when FLAT)
    arm_range                : float — anchor extension from first to current extreme (re-arm depth)
    arm_index                : int   — integer bar position of the current extreme (-1 when FLAT)
    state                    : int   — 0 FLAT, +1 ARMED_LONG, -1 ARMED_SHORT

Causal: bar i uses only data <= i. Single forward pass (O(n)).
"""
import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "armed_reversal_event"
PIVOT_SOURCE = "none"

__all__ = ["armed_reversal"]

FLAT, ARMED_LONG, ARMED_SHORT = 0, 1, -1


def armed_reversal(stretch_long, stretch_short, bullish_reversal, bearish_reversal,
                   high, low, window=3, strength=None):
    idx = high.index
    sl = stretch_long.to_numpy(dtype=bool).tolist()
    ss = stretch_short.to_numpy(dtype=bool).tolist()
    br = bullish_reversal.to_numpy(dtype=bool).tolist()
    xr = bearish_reversal.to_numpy(dtype=bool).tolist()
    hi = high.to_numpy(dtype=float).tolist()
    lo = low.to_numpy(dtype=float).tolist()
    st = strength.to_numpy(dtype=float).tolist() if strength is not None else None
    n = len(hi)
    nan = float("nan")

    entry_long  = [False] * n
    entry_short = [False] * n
    o_arm_high  = [nan] * n
    o_arm_low   = [nan] * n
    o_strength  = [nan] * n
    o_bars      = [-1] * n
    o_range     = [nan] * n
    o_index     = [-1] * n
    o_state     = [0] * n

    state = FLAT
    arm_high = nan; arm_low = nan; arm_strength = nan; arm_init = nan
    arm_index = -1; bars_since = 0

    for i in range(n):
        el = False; es = False

        if state == FLAT:
            if ss[i]:                                   # arm a SHORT fade (up-spike)
                state = ARMED_SHORT
                arm_high = hi[i]; arm_init = hi[i]
                arm_strength = st[i] if st is not None else nan
                arm_index = i; bars_since = 0
            elif sl[i]:                                 # arm a LONG fade (down-flush)
                state = ARMED_LONG
                arm_low = lo[i]; arm_init = lo[i]
                arm_strength = st[i] if st is not None else nan
                arm_index = i; bars_since = 0
        elif state == ARMED_SHORT:
            if hi[i] > arm_high and ss[i]:              # re-arm: new extreme AND still stretched
                arm_high = hi[i]
                arm_strength = st[i] if st is not None else nan
                arm_index = i; bars_since = 0
            elif xr[i]:                                 # reversal -> enter
                es = True
            else:
                bars_since += 1
        else:  # ARMED_LONG
            if lo[i] < arm_low and sl[i]:
                arm_low = lo[i]
                arm_strength = st[i] if st is not None else nan
                arm_index = i; bars_since = 0
            elif br[i]:
                el = True
            else:
                bars_since += 1

        # --- record this bar (before any FLAT reset, so entry bars carry the anchor) ---
        if state == ARMED_SHORT or es:
            o_arm_high[i] = arm_high
            o_range[i]    = arm_high - arm_init
            o_strength[i] = arm_strength
            o_index[i]    = arm_index
            o_bars[i]     = bars_since
            o_state[i]    = ARMED_SHORT
        elif state == ARMED_LONG or el:
            o_arm_low[i]  = arm_low
            o_range[i]    = arm_init - arm_low
            o_strength[i] = arm_strength
            o_index[i]    = arm_index
            o_bars[i]     = bars_since
            o_state[i]    = ARMED_LONG
        entry_long[i]  = el
        entry_short[i] = es

        # --- transitions back to FLAT ---
        if es or el:
            state = FLAT
        elif state == ARMED_SHORT and bars_since >= window:
            state = FLAT
        elif state == ARMED_LONG and bars_since >= window:
            state = FLAT

    return pd.DataFrame({
        "entry_long":         entry_long,
        "entry_short":        entry_short,
        "arm_high":           o_arm_high,
        "arm_low":            o_arm_low,
        "arm_strength":       o_strength,
        "bars_since_extreme": o_bars,
        "arm_range":          o_range,
        "arm_index":          o_index,
        "state":              o_state,
    }, index=idx)
