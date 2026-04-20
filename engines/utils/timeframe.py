"""
engines/utils/timeframe.py

Shared timeframe parsing utilities. Single source of truth for converting
pandas-style frequency strings ('5min', '15m', '1H', '1D', etc.) into
integer minute counts.

Used by:
    - indicators.momentum.macd_htf
    - engines.indicator_warmup_resolver
    - tools.run_stage1 (via resolver)

Contract:
    - Always returns whole-minute counts (no sub-minute TFs supported).
    - Malformed or unsupported frequencies raise ValueError fail-fast.
"""

import re

import pandas as pd

_UNIT_MINUTES = {
    "m": 1,
    "min": 1,
    "t": 1,  # pandas legacy alias for minute
    "h": 60,
    "d": 60 * 24,
}


def parse_freq_to_minutes(freq: str) -> int:
    """Parse a pandas-style frequency string into integer minutes.

    Accepts:
        "5min", "5m", "5T"   -> 5
        "15min", "15m"       -> 15
        "1H", "1h", "60min"  -> 60
        "1D", "1d"           -> 1440

    Raises:
        ValueError: if freq is not a string, is malformed, or uses an
            unsupported unit (weeks, months, sub-minute, etc.).
    """
    if not isinstance(freq, str):
        raise ValueError(
            f"timeframe.parse_freq_to_minutes: freq must be str, "
            f"got {type(freq).__name__}"
        )
    m = re.fullmatch(r"\s*(\d+)\s*([A-Za-z]+)\s*", freq)
    if not m:
        raise ValueError(
            f"timeframe.parse_freq_to_minutes: unrecognized freq {freq!r}"
        )
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit not in _UNIT_MINUTES:
        raise ValueError(
            f"timeframe.parse_freq_to_minutes: unsupported unit in {freq!r}. "
            f"Allowed: min/m/T, h/H, d/D"
        )
    if n <= 0:
        raise ValueError(
            f"timeframe.parse_freq_to_minutes: non-positive count in {freq!r}"
        )
    return n * _UNIT_MINUTES[unit]


def infer_base_tf_minutes(dt_index: pd.DatetimeIndex) -> int:
    """Infer base TF in integer minutes from a DatetimeIndex.

    Strict rules (fail-fast):
        - Requires >= 2 timestamps.
        - Uses the mode of timestamp deltas.
        - All modal candidates (ties) must be equal — multi-modal
          distributions indicate malformed or mixed-TF input.
        - Delta must be whole-minute resolution (>= 60s and % 60 == 0).
        - Raises ValueError on any violation; never returns a guess.

    This is a FALLBACK mechanism for call sites (e.g. the engine's
    post-load evaluation gate) that have no access to the directive
    config. It is NOT a source of truth — preflight warmup is
    config-driven. Under normal conditions the two agree; a mismatch
    indicates malformed data.
    """
    if not isinstance(dt_index, pd.DatetimeIndex):
        raise ValueError(
            f"timeframe.infer_base_tf_minutes: expected DatetimeIndex, "
            f"got {type(dt_index).__name__}"
        )
    if len(dt_index) < 2:
        raise ValueError(
            "timeframe.infer_base_tf_minutes: cannot infer base TF from < 2 timestamps"
        )
    deltas = dt_index.to_series().diff().dropna()
    if deltas.empty:
        raise ValueError("timeframe.infer_base_tf_minutes: empty delta series")
    modes = deltas.mode()
    if len(modes) > 1 and len(set(modes.tolist())) > 1:
        raise ValueError(
            f"timeframe.infer_base_tf_minutes: ambiguous base TF — multiple "
            f"modal deltas {[str(m) for m in modes.tolist()]}. "
            f"Input appears to mix timeframes or is malformed."
        )
    mode_delta = modes.iloc[0]
    seconds = int(mode_delta.total_seconds())
    if seconds <= 0 or seconds % 60 != 0:
        raise ValueError(
            f"timeframe.infer_base_tf_minutes: base TF delta {mode_delta} "
            f"is not a whole-minute interval"
        )
    return seconds // 60
