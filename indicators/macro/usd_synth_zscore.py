"""
usd_synth_zscore.py — USD Synthetic Index Z-Score Macro Direction Filter

External Dependency:
    Requires USD_SYNTH daily close data at:
    data_root/SYSTEM_FACTORS/USD_SYNTH/usd_synth_close_d1.csv

    Expected CSV columns: Date, USD_SYNTH_CLOSE_D1

Output columns:
    usd_z_score    : float — rolling Z-score of USD_SYNTH (lookback-day window)
    macro_allowed  : int   — +1 (allow longs only), -1 (allow shorts only), 0 (no trade)

Mean-Reversion Logic:
    Z >= +threshold  -> USD overbought -> fade -> USD should weaken
        quote pairs (neg corr with USD) rise  -> allow LONG  (+1)
        base pairs  (pos corr with USD) fall  -> allow SHORT (-1)
    Z <= -threshold  -> USD oversold   -> fade -> USD should strengthen
        quote pairs fall  -> allow SHORT (-1)
        base pairs  rise  -> allow LONG  (+1)
    |Z| < threshold  -> neutral zone   -> no trades (0)

Lookahead Safety:
    Z-score uses previous day's completed close (shift(1)).
    Pair correlation computed from full overlap — static property, not forward-looking.

Output Scale:
    usd_z_score   : unbounded float (typically -3 to +3)
    macro_allowed : {-1, 0, +1}
"""

from pathlib import Path
import pandas as pd
import numpy as np

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "zscore_synthetic"
PIVOT_SOURCE = "none"


# =============================================================================
# GOVERNANCE: External Dependency Isolation
# =============================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

USD_SYNTH_CLOSE_PATH = (
    _PROJECT_ROOT
    / "data_root"
    / "SYSTEM_FACTORS"
    / "USD_SYNTH"
    / "usd_synth_close_d1.csv"
)


def usd_synth_zscore(
    df: pd.DataFrame,
    lookback: int = 100,
    threshold: float = 1.5,
) -> pd.DataFrame:
    """
    Add USD_SYNTH Z-score macro direction filter columns to a price DataFrame.

    Args:
        df:        DataFrame with 'time' (or first col) and 'close' columns.
                   Typically intraday (15m/1h/4h) OHLCV data for a single pair.
        lookback:  Rolling window for Z-score computation (default 100 days).
        threshold: Minimum |Z| to generate a trade signal (default 1.5).

    Returns:
        df with two new columns: 'usd_z_score', 'macro_allowed'.
        Original index is preserved.
    """
    # ------------------------------------------------------------------
    # 1. Load USD_SYNTH daily close
    # ------------------------------------------------------------------
    if not USD_SYNTH_CLOSE_PATH.exists():
        raise FileNotFoundError(
            f"usd_synth_zscore: Required data file not found at:\n"
            f"  {USD_SYNTH_CLOSE_PATH}\n"
            f"Ensure USD_SYNTH dataset is present under "
            f"data_root/SYSTEM_FACTORS/USD_SYNTH/."
        )

    usd = pd.read_csv(USD_SYNTH_CLOSE_PATH, encoding="utf-8")
    usd["Date"] = pd.to_datetime(usd["Date"])
    usd = usd.sort_values("Date").reset_index(drop=True)

    close_col = "USD_SYNTH_CLOSE_D1"

    # ------------------------------------------------------------------
    # 2. Compute rolling Z-score
    # ------------------------------------------------------------------
    _vals = usd[close_col].values.astype(float)
    _mean = usd[close_col].rolling(lookback).mean()
    _std = usd[close_col].rolling(lookback).std(ddof=0)
    _std = _std.replace(0, np.nan)  # prevent div-by-zero

    usd["usd_z_score"] = (_vals - _mean) / _std

    # Lag by 1 day — no look-ahead
    usd["usd_z_score"] = usd["usd_z_score"].shift(1)

    # ------------------------------------------------------------------
    # 3. Detect pair type via correlation with USD_SYNTH
    # ------------------------------------------------------------------
    time_col = "time" if "time" in df.columns else df.columns[0]
    df_dates = pd.to_datetime(df[time_col])

    pair_daily = df.copy()
    pair_daily["_date"] = df_dates.dt.normalize()
    pair_eod = pair_daily.groupby("_date")["close"].last()

    usd_indexed = usd.set_index("Date")[close_col]
    common_dates = pair_eod.index.intersection(usd_indexed.index)

    if len(common_dates) > 30:
        pair_ret = pair_eod[common_dates].pct_change().dropna()
        usd_ret = usd_indexed[common_dates].pct_change().dropna()
        common_ret = pair_ret.index.intersection(usd_ret.index)
        corr = pair_ret[common_ret].corr(usd_ret[common_ret])
    else:
        corr = -1  # default to quote-pair behaviour

    # pair_sign: -1 for quote pairs (EURUSD, GBPUSD, AUDUSD)
    #            +1 for base pairs  (USDJPY, USDCAD, USDCHF)
    pair_sign = -1 if corr < 0 else 1

    # ------------------------------------------------------------------
    # 4. Map Z-score to macro_allowed direction signal
    # ------------------------------------------------------------------
    z = usd["usd_z_score"].values
    # z_signal: +1 when USD overbought (fade down), -1 when oversold (fade up)
    z_signal = np.where(z >= threshold, 1, np.where(z <= -threshold, -1, 0))
    # macro_allowed = -pair_sign * z_signal
    #   USD overbought + quote pair -> +1 (long)
    #   USD overbought + base pair  -> -1 (short)
    usd["macro_allowed"] = (-pair_sign * z_signal).astype(int)

    # ------------------------------------------------------------------
    # 5. Merge onto intraday data by date (preserves df index)
    # ------------------------------------------------------------------
    usd_signal = usd[["Date", "usd_z_score", "macro_allowed"]].copy()
    usd_signal = usd_signal.rename(columns={"Date": "_merge_date"})
    macro_map = usd_signal.set_index("_merge_date")["macro_allowed"]
    zscore_map = usd_signal.set_index("_merge_date")["usd_z_score"]

    merge_dates = df_dates.dt.normalize()
    df["usd_z_score"] = merge_dates.map(zscore_map).values
    df["macro_allowed"] = merge_dates.map(macro_map).fillna(0).astype(int).values

    return df
