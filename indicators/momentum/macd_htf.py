"""
macd_htf.py

Higher-timeframe MACD as a multi-dimensional signal provider, with
timeframe-suffixed columns to prevent collisions across multi-TF calls.

Execution order (strict):
    1. Resample close to resample_freq (last)
    2. Compute MACD on resampled series
    3. Derive crossover / cross_event / momentum / acceleration / bias
       on resampled series
    4. Apply warmup mask on resampled derived columns (pre-shift)
    5. shift(1) on all columns (no lookahead)
    6. Reindex to intraday series index, ffill
    7. Apply derived zero-mask on intraday frame where
       original resampled row was NaN OR within warmup

Invariants:
    - Raw columns (line/signal/hist) never fabricated, never backfilled.
      Leading intraday rows may remain NaN if HTF warmup has not elapsed.
    - HTF must be an integer multiple of the base TF:
          htf_minutes % base_tf_minutes == 0
      Otherwise ValueError is raised.
    - Suffixes are lowercase canonical:
          3min/3m/3T   -> _3m
          5min/5m/5T   -> _5m
          15min/15m/15T-> _15m
          1H/1h/60min  -> _1h
          1D/1d        -> _1d
      Unrecognized freqs raise ValueError.
"""

import numpy as np
import pandas as pd

from engines.utils.timeframe import parse_freq_to_minutes, infer_base_tf_minutes

SIGNAL_PRIMITIVE = "macd_multidim_htf"
PIVOT_SOURCE = "none"


def _tf_suffix(freq: str) -> str:
    """Lowercase canonical suffix: _3m / _15m / _1h / _1d."""
    mins = parse_freq_to_minutes(freq)
    if mins % (60 * 24) == 0:
        return f"_{mins // (60 * 24)}d"
    if mins % 60 == 0:
        return f"_{mins // 60}h"
    return f"_{mins}m"


def _canonical_pandas_freq(freq: str) -> str:
    """Emit a pandas-accepted resample rule for the parsed minutes."""
    mins = parse_freq_to_minutes(freq)
    if mins % (60 * 24) == 0:
        return f"{mins // (60 * 24)}D"
    if mins % 60 == 0:
        return f"{mins // 60}h"
    return f"{mins}min"


def macd_htf(
    series_or_df,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    resample_freq: str = "15min",
) -> pd.DataFrame:
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("macd_htf: fast, slow, signal must be positive")
    if fast >= slow:
        raise ValueError(f"macd_htf: fast ({fast}) must be < slow ({slow})")

    # --- accept Series or engine-format DataFrame ---
    if isinstance(series_or_df, pd.DataFrame):
        df = series_or_df
        if "close" not in df.columns:
            raise ValueError("macd_htf: DataFrame input requires 'close' column")
        if isinstance(df.index, pd.DatetimeIndex):
            ts_idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
        else:
            if "timestamp" not in df.columns:
                raise ValueError(
                    "macd_htf: DataFrame input needs DatetimeIndex or 'timestamp' column"
                )
            ts_idx = pd.to_datetime(df["timestamp"], utc=True)
        series = pd.Series(df["close"].astype(float).values, index=ts_idx)
    else:
        series = series_or_df
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError(
                "macd_htf: Series input requires DatetimeIndex"
            )
        series = series.astype(float)

    # --- divisibility enforcement ---
    base_tf_minutes = infer_base_tf_minutes(series.index)
    htf_minutes = parse_freq_to_minutes(resample_freq)
    if htf_minutes < base_tf_minutes:
        raise ValueError(
            f"macd_htf: HTF too small — requested={htf_minutes}m, "
            f"base_tf={base_tf_minutes}m, resample_freq={resample_freq!r}. "
            f"HTF must be >= base TF."
        )
    remainder = htf_minutes % base_tf_minutes
    if remainder != 0:
        nearest_lo = (htf_minutes // base_tf_minutes) * base_tf_minutes
        nearest_hi = nearest_lo + base_tf_minutes
        raise ValueError(
            f"macd_htf: HTF not divisible by base TF — "
            f"requested={htf_minutes}m, base_tf={base_tf_minutes}m, "
            f"remainder={remainder}m, resample_freq={resample_freq!r}. "
            f"Nearest valid HTFs: {nearest_lo}m or {nearest_hi}m."
        )

    suffix = _tf_suffix(resample_freq)
    rule = _canonical_pandas_freq(resample_freq)

    # --- 1. resample ---
    htf_close = series.resample(rule).last().dropna()
    n_htf = len(htf_close)
    if n_htf == 0:
        raise ValueError(f"macd_htf: resample to {rule} produced empty series")

    # --- 2. compute MACD on resampled series ---
    ema_fast = htf_close.ewm(span=fast, adjust=False).mean()
    ema_slow = htf_close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal_line

    line_v = macd_line.values
    sig_v = macd_signal_line.values
    hist_v = macd_hist.values

    # --- 3. derive dimensions on resampled series ---
    crossover = np.zeros(n_htf, dtype=np.int8)
    crossover[line_v > sig_v] = 1
    crossover[line_v < sig_v] = -1

    bias = np.zeros(n_htf, dtype=np.int8)
    bias[line_v > 0.0] = 1
    bias[line_v < 0.0] = -1

    cross_event = np.zeros(n_htf, dtype=np.int8)
    if n_htf > 1:
        up = (crossover[1:] == 1) & (crossover[:-1] == -1)
        dn = (crossover[1:] == -1) & (crossover[:-1] == 1)
        cross_event[1:][up] = 1
        cross_event[1:][dn] = -1

    acceleration = np.diff(hist_v, prepend=np.nan)
    acceleration = np.nan_to_num(acceleration, nan=0.0)

    momentum = hist_v.copy()

    # --- 4. warmup mask on derived signals (pre-shift) ---
    warmup = slow + signal
    if warmup > 0:
        w = min(warmup, n_htf)
        crossover[:w] = 0
        cross_event[:w] = 0
        bias[:w] = 0
        acceleration[:w] = 0.0
        # momentum intentionally NOT masked (raw equivalence)

    htf_frame = pd.DataFrame(
        {
            f"macd_line{suffix}": line_v,
            f"macd_signal{suffix}": sig_v,
            f"macd_hist{suffix}": hist_v,
            f"macd_crossover{suffix}": crossover.astype(np.int8),
            f"macd_cross_event{suffix}": cross_event.astype(np.int8),
            f"macd_momentum{suffix}": momentum,
            f"macd_acceleration{suffix}": acceleration,
            f"macd_bias{suffix}": bias.astype(np.int8),
        },
        index=htf_close.index,
    )

    # --- 5. shift(1) for no-lookahead ---
    htf_shifted = htf_frame.shift(1)

    # --- 6. reindex to intraday, ffill ---
    mapped = htf_shifted.reindex(series.index, method="ffill")

    # --- 7. post-ffill warmup mask on derived columns ---
    # A derived column is invalid at an intraday bar if the last valid
    # HTF row mapped onto it was within the warmup window. We rebuild
    # an "htf row index" per intraday bar to detect this.
    htf_positions = pd.Series(
        np.arange(n_htf, dtype=np.int64),
        index=htf_close.index,
    )
    # shift(1) matches the shift applied to htf_frame above
    htf_positions_shifted = htf_positions.shift(1)
    mapped_pos = htf_positions_shifted.reindex(
        series.index, method="ffill"
    )

    invalid = mapped_pos.isna() | (mapped_pos < warmup)

    int_derived = [
        f"macd_crossover{suffix}",
        f"macd_cross_event{suffix}",
        f"macd_bias{suffix}",
    ]
    float_derived = [f"macd_acceleration{suffix}"]

    for col in int_derived:
        mapped.loc[invalid, col] = 0
        mapped[col] = mapped[col].fillna(0).astype(np.int8)

    for col in float_derived:
        mapped.loc[invalid, col] = 0.0
        mapped[col] = mapped[col].fillna(0.0).astype(float)

    # momentum: leave NaN where HTF has not yet produced a bar (raw equivalence);
    # do NOT fabricate.
    # Raw columns (line/signal/hist): leading NaN preserved by design.

    return mapped


def time_requirement(params: dict, tf_minutes: int) -> int:
    """tf_minutes here is the HTF minutes (not the base TF)."""
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    return (slow + signal) * int(tf_minutes)
