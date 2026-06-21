import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "internal_bar_strength"
PIVOT_SOURCE = "none"


def ibs(df: pd.DataFrame) -> pd.Series:
    """
    Internal Bar Strength (IBS): the position of the close within the bar's range.

        IBS = (close - low) / (high - low)

    Ranges [0, 1]: 0 when the close is the bar's low, 1 when it is the high.
    Equivalent to a 1-period Stochastic. Zero-range bars (high == low) divide by
    zero and are set to 0.5 (neutral). Zero warmup — single-bar computation, no
    look-ahead (uses only the current bar's own OHLC).

    Output Scale: [0, 1] (unitless fraction of the bar's range).

    Args:
        df: DataFrame containing 'high', 'low', 'close' columns

    Returns:
        pd.Series: IBS values in [0, 1]
    """
    high_low = df['high'] - df['low']
    ibs_raw = (df['close'] - df['low']) / high_low.where(high_low != 0, np.nan)
    return ibs_raw.fillna(0.5)
