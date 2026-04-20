"""
macd.py

MACD as a multi-dimensional signal provider.

Emits four orthogonal signal dimensions plus the raw components.
No aggregation, no thresholding, no composite regime. Strategy layer
composes dimensions as needed.

Dimensions:
  - macd_crossover   : state of line vs signal        {-1, 0, +1}
  - macd_cross_event : transition event (this bar)    {-1, 0, +1}
  - macd_momentum    : signed magnitude (= macd_hist)  float
  - macd_acceleration: change in momentum              float
  - macd_bias        : state of line vs zero-line     {-1, 0, +1}

Raw components (never masked): macd_line, macd_signal, macd_hist.

Warmup = slow + signal.
  - Derived signals (crossover, cross_event, acceleration, bias) -> 0 in warmup.
  - Raw components untouched.
  - First post-warmup acceleration NaN -> 0 (no NaN leak).

Acceleration semantics:
  Positive acceleration means momentum is *increasing*, not bullish;
  negative means momentum is *decreasing*, not bearish. Must be paired
  with `macd_momentum` or `macd_bias` for directional meaning. Never
  use standalone.
"""

import numpy as np
import pandas as pd

SIGNAL_PRIMITIVE = "macd_multidim"
PIVOT_SOURCE = "none"


def macd(
    series_or_df,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("macd: fast, slow, signal must be positive")
    if fast >= slow:
        raise ValueError(f"macd: fast ({fast}) must be < slow ({slow})")

    # --- accept Series or engine-format DataFrame ---
    if isinstance(series_or_df, pd.DataFrame):
        if "close" not in series_or_df.columns:
            raise ValueError("macd: DataFrame input requires 'close' column")
        series = series_or_df["close"]
    else:
        series = series_or_df

    series = series.astype(float)
    n = len(series)
    warmup = slow + signal

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal_line

    line_v = macd_line.values
    sig_v = macd_signal_line.values
    hist_v = macd_hist.values

    # --- derived dimensions ---

    crossover = np.zeros(n, dtype=np.int8)
    crossover[line_v > sig_v] = 1
    crossover[line_v < sig_v] = -1

    bias = np.zeros(n, dtype=np.int8)
    bias[line_v > 0.0] = 1
    bias[line_v < 0.0] = -1

    # cross_event: explicit state-transition definition, not diff magnitude
    cross_event = np.zeros(n, dtype=np.int8)
    if n > 1:
        up = (crossover[1:] == 1) & (crossover[:-1] == -1)
        dn = (crossover[1:] == -1) & (crossover[:-1] == 1)
        cross_event[1:][up] = 1
        cross_event[1:][dn] = -1

    # acceleration: first difference of histogram, NaN -> 0
    acceleration = np.diff(hist_v, prepend=np.nan)
    acceleration = np.nan_to_num(acceleration, nan=0.0)

    # momentum: alias of raw histogram (kept as a dedicated column for API clarity)
    momentum = hist_v.copy()

    # --- warmup mask on derived signals only ---
    if warmup > 0:
        w = min(warmup, n)
        crossover[:w] = 0
        cross_event[:w] = 0
        bias[:w] = 0
        acceleration[:w] = 0.0
        # momentum intentionally NOT masked -- it equals raw hist by contract

    return pd.DataFrame(
        {
            "macd_line": line_v,
            "macd_signal": sig_v,
            "macd_hist": hist_v,
            "macd_crossover": crossover,
            "macd_cross_event": cross_event,
            "macd_momentum": momentum,
            "macd_acceleration": acceleration,
            "macd_bias": bias,
        },
        index=series.index,
    )


def time_requirement(params: dict, tf_minutes: int) -> int:
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    return (slow + signal) * int(tf_minutes)
