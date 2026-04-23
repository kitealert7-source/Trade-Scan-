import pandas as pd
import numpy as np

from indicators.volatility.atr import atr

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "wilder_rma_tr_floored"
PIVOT_SOURCE = "none"


def atr_with_pip_floor(
    df: pd.DataFrame,
    window: int,
    min_pips: float,
    pip_size: float,
    sl_atr_mult: float,
) -> pd.Series:
    """ATR floored so that (atr * sl_atr_mult) >= (min_pips * pip_size).

    Currency-pair analogue of atr_with_dollar_floor. Floor is expressed in
    pips and converted to price units via pip_size (e.g. 0.0001 for EURUSD,
    0.01 for JPY pairs). The engine reads `pe['atr'] * sl_atr_mult` for stop
    placement, so flooring ATR to (min_pips * pip_size / sl_atr_mult)
    guarantees stop distance >= min_pips * pip_size.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns.
        window: ATR lookback.
        min_pips: Minimum stop distance in pips.
        pip_size: Price units per pip (0.0001 for 5-decimal FX pairs,
            0.01 for JPY pairs).
        sl_atr_mult: The strategy's SL ATR multiplier. Must match the engine's
            sl_cfg.atr_multiplier or the floor will be miscalibrated.

    Returns:
        pd.Series: floored ATR values.
    """
    raw = atr(df, window=window)
    floor = (float(min_pips) * float(pip_size)) / float(sl_atr_mult)
    return np.maximum(raw, floor)
