"""
spread_sma_cross.py

SMA crossover detector on z-normalized prices of two series.

Purpose
-------
For pair strategies that detect regime alignment via the relative
positioning of two price series in z-space. When the rolling z-score
of series A crosses the rolling z-score of series B (each smoothed by
an SMA), the cross marks a relative-momentum transition between the
two pairs.

The output is designed to be joined onto each leg's DataFrame by
basket_data_loader, so the recycle rule and leg strategy can read
the cross state per bar.

Used by
-------
- tools.recycle_rules.h3_spread_v1 — runtime detection of reverse-cross
  exit for the H3 USD-spread basket.
- Custom leg strategies (e.g. SpreadCrossLeg) — entry trigger on
  cross_event matching the leg's directive direction.

Implementation notes
--------------------
- Z-normalization is rolling: z = (x - rolling_mean) / rolling_std
  over `z_window` bars. NaN during warmup.
- SMA(N) applied AFTER z-normalization, on the z series.
- Cross detection compares SMA(z_a) vs SMA(z_b): sign of the diff
  defines the "side"; the bar where side flips is the "event".
- Lookahead-safe (only past data used).
- Vectorized.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def spread_sma_cross(
    series_a: pd.Series,
    series_b: pd.Series,
    z_window: int = 200,
    sma_window: int = 5,
) -> pd.DataFrame:
    """Compute SMA crossover signal between two z-normalized price series.

    Args:
        series_a: price series (e.g. close), indexed by timestamp.
        series_b: price series (e.g. close), indexed by timestamp. Must
            share the same index as series_a; misaligned rows produce
            NaN.
        z_window: rolling window length for z-normalization in bars.
            NaN for the first `z_window` bars.
        sma_window: SMA period applied on top of the z-series.

    Returns:
        pd.DataFrame indexed identically to series_a, with columns:
            z_a: rolling z-score of series_a
            z_b: rolling z-score of series_b
            sma_z_a: SMA(sma_window) of z_a
            sma_z_b: SMA(sma_window) of z_b
            diff: sma_z_a - sma_z_b (positive when A is above B)
            cross_side: +1 when diff > 0, -1 when diff < 0, 0 otherwise (NaN warmup)
            cross_event: +1 on bar where side flips from <=0 to +1
                        -1 on bar where side flips from >=0 to -1
                        0 otherwise

    Notes:
        - cross_side is the current state of the two SMAs. The recycle
          rule reads this to detect reverse-cross exit (cross_side has
          inverted from the basket's entry direction).
        - cross_event fires exactly once per crossover. The leg strategy
          reads this to trigger entry (matching directive direction).
        - The first valid output is at row index z_window + sma_window
          (warmup of both stages).
    """
    if z_window < 2:
        raise ValueError(f"spread_sma_cross.z_window must be >= 2; got {z_window}")
    if sma_window < 1:
        raise ValueError(f"spread_sma_cross.sma_window must be >= 1; got {sma_window}")

    a = pd.to_numeric(series_a, errors="coerce").astype(float)
    b = pd.to_numeric(series_b, errors="coerce").astype(float)

    # Z-normalize each (rolling)
    z_a = (a - a.rolling(z_window).mean()) / a.rolling(z_window).std()
    z_b = (b - b.rolling(z_window).mean()) / b.rolling(z_window).std()

    # SMA on the z-series
    sma_z_a = z_a.rolling(sma_window).mean()
    sma_z_b = z_b.rolling(sma_window).mean()
    diff = sma_z_a - sma_z_b

    # Side: +1, -1, or 0 (0 only during warmup)
    cross_side = pd.Series(0, index=a.index, dtype=int)
    cross_side[diff > 0] = 1
    cross_side[diff < 0] = -1

    # Event: bar where side transitions
    # +1 event: previous side was <=0, current is +1
    # -1 event: previous side was >=0, current is -1
    prev_side = cross_side.shift(1, fill_value=0)
    cross_event = pd.Series(0, index=a.index, dtype=int)
    cross_event[(cross_side == 1) & (prev_side <= 0)] = 1
    cross_event[(cross_side == -1) & (prev_side >= 0)] = -1

    out = pd.DataFrame(
        {
            "z_a": z_a,
            "z_b": z_b,
            "sma_z_a": sma_z_a,
            "sma_z_b": sma_z_b,
            "diff": diff,
            "cross_side": cross_side,
            "cross_event": cross_event,
        },
        index=a.index,
    )
    return out


__all__ = ["spread_sma_cross"]
