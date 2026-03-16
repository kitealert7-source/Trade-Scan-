
"""
realized_vol.py

Realized volatility indicator.

Purpose
-------
Compute statistical volatility from log returns.
Useful for volatility regime detection and comparison with ATR-style measures.

Implementation notes
--------------------
- Uses log returns
- Rolling standard deviation
- Optional percentile normalization
- Lookahead safe
"""

import numpy as np
import pandas as pd


def realized_vol(series: pd.Series,
                 window: int = 20,
                 percentile_window: int = 200) -> pd.DataFrame:

    series = pd.to_numeric(series, errors="coerce").astype(float)

    log_price = np.log(series.where(series > 0))

    log_ret = log_price.diff()

    rv = log_ret.rolling(window=window, min_periods=window).std()

    # percentile normalization
    def percentile_rank(x):
        if np.isnan(x[-1]):
            return np.nan
        return (x <= x[-1]).mean()

    rv_percentile = rv.rolling(percentile_window, min_periods=percentile_window).apply(percentile_rank, raw=True)

    return pd.DataFrame({
        "realized_vol": rv.values,
        "rv_percentile": rv_percentile.values
    }, index=series.index)
