"""
Linear Regression Regime HTF — Adaptive Resample (Engine-Compatible)
---------------------------------------------------------------------
Computes regression on a higher-timeframe resample of the close series.
Default: daily (1D). Supports weekly (1W) and monthly (1ME) for higher
regime timeframes (e.g. 1D regime → weekly resample, 1W regime → monthly).

- Resamples close to resample_freq (default '1D')
- Computes regression on resampled closes
- Shifts by 1 period (no lookahead)
- Forward-fills back to input resolution

v1.5.4: Added resample_freq parameter (was hardcoded to '1D').
"""

import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "linear_regression_slope_htf"
PIVOT_SOURCE = "none"


def linreg_regime_htf(series_or_df, window: int = 50, resample_freq: str = "1D") -> pd.DataFrame:
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

    # --- Build HTF Close (Daily by default, Weekly/Monthly for higher regime TFs) ---
    daily_close = series.resample(resample_freq).last().dropna()

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

    # --- Map back to input resolution ---
    intraday_dates = series.index.normalize()
    daily_result.index = daily_result.index.normalize()

    mapped = daily_result.reindex(intraday_dates, method='ffill')
    mapped.index = series.index

    return mapped