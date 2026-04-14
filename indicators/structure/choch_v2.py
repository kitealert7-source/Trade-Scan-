"""
CHOCH V2 — True Pivot-Based Change of Character

Consumes confirmed symmetric swing pivots from
indicators.structure.swing_pivots and emits CHOCH events when close breaks
the most recently confirmed counter-side pivot.

Key difference from the V1 (rolling-max proxy) impl in
indicators.structure.choch:
    V1 uses `highest_high = rolling(20).max().shift(3)` — a one-sided
    rolling-max proxy. V2 uses true symmetric pivots (k=3) with right-side
    confirmation (no repainting after confirmation).

Semantics:
    Bullish CHOCH (+1): close > last confirmed pivot_high_price
    Bearish CHOCH (-1): close < last confirmed pivot_low_price

A pivot is "confirmed" k bars after it prints. The pivot reference used at
bar i is the most recent pivot whose confirmation bar (pivot bar + k) is
<= i, i.e. only pivots that have fully materialized by bar i are
considered. This prevents any forward leakage.

Edge-triggered: consecutive bars still beyond the same pivot are suppressed;
only the first break prints.

Required input columns:
    ['high', 'low', 'close']

Output columns:
    pivot_high_flag, pivot_low_flag, pivot_high_price, pivot_low_price
        (from swing_pivots — added if not already present)
    last_pivot_high_ref  — float: the pivot_high reference used for break test
    last_pivot_low_ref   — float: the pivot_low  reference used for break test
    choch_event_v2_raw   — int {-1,0,+1}: raw break (before edge filter)
    choch_event_v2       — int {-1,0,+1}: edge-triggered break events only
"""

import numpy as np
import pandas as pd

from indicators.structure.swing_pivots import compute_swing_pivots

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "pivot_k3"
PIVOT_SOURCE = "swing_pivots_k3"

_K = 3  # must match swing_pivots._K — confirmation delay


def compute_choch_v2(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot-based CHOCH detection (V2)."""
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
    raw = np.zeros(n, dtype=int)

    current_ph = np.nan
    current_pl = np.nan

    for i in range(n):
        # A pivot at bar j is "confirmed" at bar j + K. At bar i we can
        # safely consult any pivot where j + K <= i, i.e. j <= i - K.
        j = i - _K
        if j >= 0:
            if ph_flag[j] == 1:
                current_ph = ph_price[j]
            if pl_flag[j] == 1:
                current_pl = pl_price[j]

        last_ph_ref[i] = current_ph
        last_pl_ref[i] = current_pl

        if not np.isnan(current_ph) and close[i] > current_ph:
            raw[i] = 1
        elif not np.isnan(current_pl) and close[i] < current_pl:
            raw[i] = -1
        else:
            raw[i] = 0

    # Edge-triggered filter: only emit on transition from 0 → non-zero.
    prev = np.concatenate(([0], raw[:-1]))
    event = np.where((raw != 0) & (prev == 0), raw, 0).astype(int)

    df['last_pivot_high_ref'] = last_ph_ref
    df['last_pivot_low_ref']  = last_pl_ref
    df['choch_event_v2_raw']  = raw
    df['choch_event_v2']      = event
    return df


# Public alias — matches module-tail convention used by the strategy
# provisioner (from indicators.structure.choch_v2 import choch_v2).
choch_v2 = compute_choch_v2
