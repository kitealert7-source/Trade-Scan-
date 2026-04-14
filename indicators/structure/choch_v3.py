"""
CHOCH V3 — Structure-Aware Pivot-Based Change of Character

Extends V2 (pivot-break) by requiring a prior directional structure
(HH+HL for uptrend, LL+LH for downtrend) before a counter-side break
qualifies as a CHOCH.

Semantics:
    Bullish CHOCH (+1): has_downtrend AND close > last confirmed pivot_high
    Bearish CHOCH (-1): has_uptrend   AND close < last confirmed pivot_low

Structure tracking (minimal, last-two-pivots only):
    Each time a new confirmed pivot lands, re-evaluate structure using the
    latest two pivot_highs and latest two pivot_lows:
        HH = last_pivot_high > prev_pivot_high
        HL = last_pivot_low  > prev_pivot_low
        LH = last_pivot_high < prev_pivot_high
        LL = last_pivot_low  < prev_pivot_low

        HH AND HL  -> has_uptrend=True,  has_downtrend=False
        LL AND LH  -> has_downtrend=True, has_uptrend=False
        (otherwise flags retain prior value — sticky until opposing
         structure is seen)

Confirmation delay: k=3 (no forward leakage).
Edge-triggered: only first bar of a break prints.

Output columns added:
    last_pivot_high_ref, last_pivot_low_ref
    has_uptrend, has_downtrend          (int 0/1)
    choch_event_v3_raw, choch_event_v3  (int -1/0/+1)
"""

import numpy as np
import pandas as pd

from indicators.structure.swing_pivots import compute_swing_pivots

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "structure_gated"
PIVOT_SOURCE = "swing_pivots_k3"

_K = 3  # must match swing_pivots._K


def compute_choch_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Structure-aware pivot-based CHOCH detection (V3)."""
    if 'pivot_high_flag' not in df.columns:
        df = compute_swing_pivots(df)

    n = len(df)
    close = df['close'].to_numpy(dtype=float)
    ph_flag = df['pivot_high_flag'].to_numpy(dtype=int)
    pl_flag = df['pivot_low_flag'].to_numpy(dtype=int)
    ph_price = df['pivot_high_price'].to_numpy(dtype=float)
    pl_price = df['pivot_low_price'].to_numpy(dtype=float)

    last_ph_ref = np.full(n, np.nan, dtype=float)
    last_pl_ref = np.full(n, np.nan, dtype=float)
    has_up_out = np.zeros(n, dtype=int)
    has_dn_out = np.zeros(n, dtype=int)
    raw = np.zeros(n, dtype=int)

    last_ph = np.nan
    prev_ph = np.nan
    last_pl = np.nan
    prev_pl = np.nan

    has_uptrend = False
    has_downtrend = False

    def _update_structure():
        nonlocal has_uptrend, has_downtrend
        if np.isnan(prev_ph) or np.isnan(last_ph) or np.isnan(prev_pl) or np.isnan(last_pl):
            return
        hh = last_ph > prev_ph
        hl = last_pl > prev_pl
        lh = last_ph < prev_ph
        ll = last_pl < prev_pl
        if hh and hl:
            has_uptrend = True
            has_downtrend = False
        elif ll and lh:
            has_downtrend = True
            has_uptrend = False

    for i in range(n):
        # Pivot at bar j is usable once j + K <= i, i.e. j <= i - K.
        j = i - _K
        if j >= 0:
            if ph_flag[j] == 1:
                prev_ph = last_ph
                last_ph = ph_price[j]
                _update_structure()
            if pl_flag[j] == 1:
                prev_pl = last_pl
                last_pl = pl_price[j]
                _update_structure()

        last_ph_ref[i] = last_ph
        last_pl_ref[i] = last_pl
        has_up_out[i] = 1 if has_uptrend else 0
        has_dn_out[i] = 1 if has_downtrend else 0

        if has_downtrend and not np.isnan(last_ph) and close[i] > last_ph:
            raw[i] = 1
        elif has_uptrend and not np.isnan(last_pl) and close[i] < last_pl:
            raw[i] = -1
        else:
            raw[i] = 0

    prev = np.concatenate(([0], raw[:-1]))
    event = np.where((raw != 0) & (prev == 0), raw, 0).astype(int)

    df['last_pivot_high_ref'] = last_ph_ref
    df['last_pivot_low_ref']  = last_pl_ref
    df['has_uptrend']         = has_up_out
    df['has_downtrend']       = has_dn_out
    df['choch_event_v3_raw']  = raw
    df['choch_event_v3']      = event
    return df


choch_v3 = compute_choch_v3
