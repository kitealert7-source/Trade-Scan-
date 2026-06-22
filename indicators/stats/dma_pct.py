"""
Distance from Moving Average (DMA%) — percentage stretch of price from a short SMA.

    DMA%(n) = (close - SMA(n)) / SMA(n) * 100

The MA-distance member of the mean-reversion stretch family (vault
[[mean-reversion-stretch-signals]]): how far price has stretched from its own
short-term mean, as a percent of that mean. Negative = price below the MA
(oversold / long-fade setup), positive = above (overbought / short-fade setup).

Distinct from the sigma-normalized z-score (indicators.stats.rolling_zscore, the
spread-distance cousin) and range-location IBS — this normalizes by price LEVEL,
not by volatility. Two roles from one function via the window arg:
  - dma_pct(df, 20)  -> the fade signal AND the return-to-mean exit (crosses 0)
  - dma_pct(df, 200) -> the regime gate: dma_pct(.,200) > 0  <=>  close > SMA(200)

Causal: close[t] and SMA over [t-n+1 .. t]; no look-ahead. NaN for the first n-1
warmup bars and wherever SMA == 0.

(The volatility-normalized variant — distance in ATR units, for the ATR-multiple
trigger — is deferred to the ATR-distance sweep; it will be added here as dma_atr.)
"""
import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "distance_from_moving_average_pct"
PIVOT_SOURCE = "none"

__all__ = ["dma_pct"]


def dma_pct(df: pd.DataFrame, window: int) -> pd.Series:
    """Percent distance of close from its SMA(window).

        DMA%(n) = (close - SMA(n)) / SMA(n) * 100

    Args:
        df: DataFrame with a 'close' column.
        window: SMA lookback (e.g. 20 for the signal/exit MA, 200 for the regime MA).

    Returns:
        pd.Series of percent distance; NaN during the n-1 warmup and wherever
        SMA == 0 (division guard).
    """
    close = df["close"].astype(float)
    sma = close.rolling(window=window, min_periods=window).mean()
    sma = sma.where(sma != 0, np.nan)
    return (close - sma) / sma * 100.0
