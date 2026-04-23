import pandas as pd
import numpy as np

from indicators.volatility.atr import atr

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "wilder_rma_tr_floored"
PIVOT_SOURCE = "none"


def atr_with_dollar_floor(
    df: pd.DataFrame,
    window: int,
    min_dollars: float,
    sl_atr_mult: float,
) -> pd.Series:
    """ATR floored so that (atr * sl_atr_mult) >= min_dollars.

    Returns the elementwise max of Wilder ATR and (min_dollars / sl_atr_mult).
    Used to inject a minimum stop-distance floor without engine changes:
    the engine reads `pe['atr'] * sl_atr_mult` for stop placement, so flooring
    ATR to (min_dollars / sl_atr_mult) guarantees stop distance >= min_dollars.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns.
        window: ATR lookback.
        min_dollars: Minimum stop distance in price-units (USD/oz for XAUUSD).
        sl_atr_mult: The strategy's SL ATR multiplier. Must match the engine's
            sl_cfg.atr_multiplier or the floor will be miscalibrated.

    Returns:
        pd.Series: floored ATR values.
    """
    raw = atr(df, window=window)
    floor = float(min_dollars) / float(sl_atr_mult)
    return np.maximum(raw, floor)
