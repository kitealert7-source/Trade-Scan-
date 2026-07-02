"""
Pair Ratio — synthetic ratio series from two price feeds
--------------------------------------------------------
Purpose:
    Construct a relative-value ratio series (e.g. Gold-Silver Ratio =
    XAUUSD close / XAGUSD close) from two already-loaded price Series.
    The ratio is the SIGNAL SUBSTRATE for RV strategies (percentile-band
    fades, EMA crosses on the ratio); downstream indicators (EMA,
    rolling_percentile, rolling_zscore) consume its output directly.

Alignment contract (fail-fast, Invariant #1):
    - align="strict" (default): both Series must share an IDENTICAL index;
      any mismatch raises — bar alignment is the data layer's job, and a
      silent inner-join can hide a stale/gappy feed (session-seam
      corruption is the known failure mode for 2-feed synthetics).
    - align="inner": explicit opt-in — intersect indexes first, for
      research probes where the caller has accepted the drop count.

Defaults are GENERIC (concept-harvest posture 2026-07-02).

Safe:
    - No division by zero (zero/NaN denominator -> NaN)
    - No lookahead (pointwise divide; no rolling state)
    - Fully vectorized
    - Inputs not mutated
"""

import pandas as pd
import numpy as np

# Substrate constructor, not a standalone entry signal: directives declare
# the signal indicator applied ON the ratio (e.g. rolling_percentile /
# ema_cross), so no SIGNAL_PRIMITIVE is carried here by design — same
# contract position as engine-fed context series.


def pair_ratio(
    numerator: pd.Series,
    denominator: pd.Series,
    align: str = "strict",
) -> pd.Series:

    if align == "strict":
        if not numerator.index.equals(denominator.index):
            raise ValueError(
                "pair_ratio(strict): index mismatch between legs "
                f"(len {len(numerator)} vs {len(denominator)}) — bar-align "
                "the feeds upstream or pass align='inner' explicitly"
            )
        num, den = numerator.astype(float), denominator.astype(float)
    elif align == "inner":
        common = numerator.index.intersection(denominator.index)
        if common.empty:
            raise ValueError("pair_ratio(inner): no overlapping index between legs")
        num = numerator.loc[common].astype(float)
        den = denominator.loc[common].astype(float)
    else:
        raise ValueError(f"unknown align {align!r} (strict | inner)")

    den_safe = den.replace(0, np.nan)
    return num / den_safe
