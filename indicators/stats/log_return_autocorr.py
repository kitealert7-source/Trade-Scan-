
"""
log_return_autocorr.py

Rolling log-return autocorrelation regime detector.

Purpose
-------
Detect whether the market exhibits momentum (positive autocorrelation)
or mean-reversion (negative autocorrelation) behavior.

Implementation notes
--------------------
- Uses log returns
- Rolling autocorrelation with lag=1
- Lookahead safe (only past data used)
- Vectorized pandas operations
"""

import numpy as np
import pandas as pd


def log_return_autocorr(series: pd.Series,
                        window: int = 50,
                        pos_threshold: float = 0.05,
                        neg_threshold: float = -0.05) -> pd.DataFrame:

    series = pd.to_numeric(series, errors="coerce").astype(float)

    log_price = np.log(series.where(series > 0))

    log_ret = log_price.diff()

    # rolling autocorrelation lag=1
    autocorr = (
        log_ret.rolling(window)
        .corr(log_ret.shift(1))
    )

    regime = np.zeros(len(series), dtype=int)

    regime[autocorr > pos_threshold] = 1
    regime[autocorr < neg_threshold] = -1

    return pd.DataFrame({
        "autocorr": autocorr.values,
        "regime": regime
    }, index=series.index)
