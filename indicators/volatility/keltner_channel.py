"""
Keltner Channel Indicator

Pure function indicator for computing Keltner Channel (EMA-based with ATR bands).
"""
import pandas as pd
import numpy as np
from .atr import atr as compute_atr


def keltner_channel(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int,
    atr_mult: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Compute Keltner Channel.
    
    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        window: Period for EMA and ATR
        atr_mult: ATR multiplier for channel width
        
    Returns:
        tuple of (kc_mid, kc_upper, kc_lower):
            kc_mid   : EMA of close
            kc_upper : mid + atr_mult * ATR
            kc_lower : mid - atr_mult * ATR
    """
    # Enforce numeric dtype
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    
    # EMA midline
    kc_mid = close.ewm(span=window, adjust=False).mean()
    
    # ATR (reuse existing implementation)
    atr_values = compute_atr(high, low, close, window)
    
    # NaN safety: replace zero ATR with NaN
    atr_safe = atr_values.replace(0, np.nan)
    
    # Channel bands
    kc_upper = kc_mid + (atr_mult * atr_safe)
    kc_lower = kc_mid - (atr_mult * atr_safe)
    
    return kc_mid, kc_upper, kc_lower
