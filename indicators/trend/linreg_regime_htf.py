"""
Linear Regression Regime HTF — True Daily (Engine-Compatible)
--------------------------------------------------------------
Computes DAILY regression internally from intraday close series.
No changes required in execution_loop.

- Uses daily resampling of close
- Computes regression on daily closes
- Shifts by 1 day (no lookahead)
- Forward-fills back to intraday
"""

import pandas as pd
import numpy as np


def linreg_regime_htf(series_or_df, window: int = 50) -> pd.DataFrame:
    """
    Accepts either:
      - pd.Series with DatetimeIndex (legacy / explicit call)
      - pd.DataFrame with integer index and 'timestamp' + 'close' columns (engine standard)
    """
    if isinstance(series_or_df, pd.DataFrame):
        df = series_or_df
        if 'close' not in df.columns:
            raise ValueError("linreg_regime_htf requires 'close' column")
        if isinstance(df.index, pd.DatetimeIndex):
            # Bridge format: timestamp is the index (set by pipeline.py:build_dataframe)
            ts_idx = df.index if df.index.tz is not None else df.index.tz_localize('UTC')
        else:
            # Engine format: timestamp is a column
            ts_idx = pd.to_datetime(df['timestamp'], utc=True)
        series = pd.Series(df['close'].values, index=ts_idx)
    else:
        series = series_or_df
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError("HTF requires DatetimeIndex or DataFrame with 'timestamp'+'close'")

    # --- Build Daily Close ---
    daily_close = series.resample('1D').last().dropna()

    x = np.arange(window)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def slope_func(y):
        y_mean = y.mean()
        return ((x - x_mean) * (y - y_mean)).sum() / denom

    slope = daily_close.rolling(
        window=window,
        min_periods=window
    ).apply(slope_func, raw=True)

    trend = daily_close.rolling(
        window=window,
        min_periods=window
    ).mean()

    regime = np.zeros(len(daily_close), dtype=int)
    regime[slope > 0] = 1
    regime[slope < 0] = -1

    # Warmup zone
    regime[:window] = 0

    # --- Prevent Lookahead ---
    slope = slope.shift(1)
    trend = trend.shift(1)
    regime = pd.Series(regime, index=daily_close.index).shift(1)

    daily_result = pd.DataFrame({
        "trend": trend,
        "slope": slope,
        "regime": regime
    })

    # --- Map back to intraday ---
    intraday_dates = series.index.normalize()
    daily_result.index = daily_result.index.normalize()

    mapped = daily_result.reindex(intraday_dates, method='ffill')
    mapped.index = series.index

    return mapped