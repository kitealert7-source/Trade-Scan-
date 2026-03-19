"""
Bollinger Band Squeeze Detector

Pure function indicator. Detects volatility squeeze from a pre-computed
ATR percentile series — capturing intraday range compression directly.
"""
import pandas as pd


def bb_squeeze(
    atr_pct_series: pd.Series,
    squeeze_window: int,
    threshold: float,
) -> pd.DataFrame:
    """
    Detect volatility squeeze from ATR percentile series.

    Squeeze is active when at least one of the last `squeeze_window` bars had
    ATR percentile below `threshold` (scale 0.0–1.0).

    Using ATR percentile (True Range based) rather than BB width (close std based)
    captures intraday range compression directly, which is the correct signal
    for a squeeze-breakout setup.

    Args:
        atr_pct_series: ATR percentile series (0.0–1.0 scale, from atr_percentile indicator)
        squeeze_window: Number of bars to look back for any squeezed bar
        threshold:      Percentile threshold (0.0–1.0) below which a bar is "squeezed"

    Returns:
        pd.DataFrame with columns:
            squeeze_active      — 1.0 if squeeze detected in window, 0.0 otherwise
            squeeze_active_prev — squeeze_active shifted by 1 bar
    """
    atr_pct_series = atr_pct_series.astype(float)

    compressed = (atr_pct_series < threshold).astype(float)
    squeeze_active = compressed.rolling(
        window=squeeze_window, min_periods=squeeze_window
    ).max()

    return pd.DataFrame({
        "squeeze_active":      squeeze_active,
        "squeeze_active_prev": squeeze_active.shift(1).fillna(0.0),
    }, index=atr_pct_series.index)
