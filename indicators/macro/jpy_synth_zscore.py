"""
jpy_synth_zscore.py — JPY Synthetic Index Z-Score Macro Direction Filter

External Dependency:
    Requires JPY_SYNTH daily close data at:
    data_root/SYSTEM_FACTORS/JPY_SYNTH/jpy_synth_close_d1.csv

    Expected CSV columns: Date, JPY_SYNTH_CLOSE_D1

Output columns:
    jpy_z_score    : float — rolling Z-score of JPY_SYNTH (lookback-day window)
    jpy_macro_allowed  : int   — +1 (allow longs only), -1 (allow shorts only), 0 (no trade)

Mean-Reversion Logic:
    Z >= +threshold  -> JPY overbought (too strong) -> fade -> JPY should weaken
        JPY-quote pairs (neg corr with JPY_SYNTH, e.g. USDJPY) rise  -> allow LONG  (+1)
        non-JPY pairs act as regime gate (weak correlation)
    Z <= -threshold  -> JPY oversold (too weak) -> fade -> JPY should strengthen
        JPY-quote pairs fall -> allow SHORT (-1)
    |Z| < threshold  -> neutral zone -> no trades (0)

Lookahead Safety:
    Z-score uses previous day's completed close (shift(1)).
    Pair correlation computed from full overlap — static property, not forward-looking.

Output Scale:
    jpy_z_score      : unbounded float (typically -3 to +3)
    jpy_macro_allowed : {-1, 0, +1}
"""

from pathlib import Path
import pandas as pd
import numpy as np


# =============================================================================
# GOVERNANCE: External Dependency Isolation
# =============================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

JPY_SYNTH_CLOSE_PATH = (
    _PROJECT_ROOT
    / "data_root"
    / "SYSTEM_FACTORS"
    / "JPY_SYNTH"
    / "jpy_synth_close_d1.csv"
)


def jpy_synth_zscore(
    df: pd.DataFrame,
    lookback: int = 100,
    threshold: float = 1.5,
) -> pd.DataFrame:
    """
    Add JPY_SYNTH Z-score macro direction filter columns to a price DataFrame.

    Args:
        df:        DataFrame with 'time' (or first col) and 'close' columns.
                   Typically intraday (15m/1h/4h) OHLCV data for a single pair.
        lookback:  Rolling window for Z-score computation (default 100 days).
        threshold: Minimum |Z| to generate a trade signal (default 1.5).

    Returns:
        df with two new columns: 'jpy_z_score', 'jpy_macro_allowed'.
        Original index is preserved.
    """
    # ------------------------------------------------------------------
    # 1. Load JPY_SYNTH daily close
    # ------------------------------------------------------------------
    if not JPY_SYNTH_CLOSE_PATH.exists():
        raise FileNotFoundError(
            f"jpy_synth_zscore: Required data file not found at:\n"
            f"  {JPY_SYNTH_CLOSE_PATH}\n"
            f"Ensure JPY_SYNTH dataset is present under "
            f"data_root/SYSTEM_FACTORS/JPY_SYNTH/."
        )

    jpy = pd.read_csv(JPY_SYNTH_CLOSE_PATH, encoding="utf-8")
    jpy["Date"] = pd.to_datetime(jpy["Date"])
    jpy = jpy.sort_values("Date").reset_index(drop=True)

    close_col = "JPY_SYNTH_CLOSE_D1"

    # ------------------------------------------------------------------
    # 2. Compute rolling Z-score
    # ------------------------------------------------------------------
    _vals = jpy[close_col].values.astype(float)
    _mean = jpy[close_col].rolling(lookback).mean()
    _std = jpy[close_col].rolling(lookback).std(ddof=0)
    _std = _std.replace(0, np.nan)  # prevent div-by-zero

    jpy["jpy_z_score"] = (_vals - _mean) / _std

    # Lag by 1 day — no look-ahead
    jpy["jpy_z_score"] = jpy["jpy_z_score"].shift(1)

    # ------------------------------------------------------------------
    # 3. Detect pair type via correlation with JPY_SYNTH
    # ------------------------------------------------------------------
    time_col = "time" if "time" in df.columns else df.columns[0]
    df_dates = pd.to_datetime(df[time_col])

    pair_daily = df.copy()
    pair_daily["_date"] = df_dates.dt.normalize()
    pair_eod = pair_daily.groupby("_date")["close"].last()

    jpy_indexed = jpy.set_index("Date")[close_col]
    common_dates = pair_eod.index.intersection(jpy_indexed.index)

    if len(common_dates) > 30:
        pair_ret = pair_eod[common_dates].pct_change().dropna()
        jpy_ret = jpy_indexed[common_dates].pct_change().dropna()
        common_ret = pair_ret.index.intersection(jpy_ret.index)
        corr = pair_ret[common_ret].corr(jpy_ret[common_ret])
    else:
        corr = -1  # default to JPY-quote pair behaviour

    # pair_sign: -1 for JPY-quote pairs (USDJPY, EURJPY — neg corr with JPY strength index)
    #            +1 for pairs positively correlated with JPY strength
    pair_sign = -1 if corr < 0 else 1

    # ------------------------------------------------------------------
    # 4. Map Z-score to jpy_macro_allowed direction signal
    # ------------------------------------------------------------------
    z = jpy["jpy_z_score"].values
    # z_signal: +1 when JPY overbought (fade down), -1 when oversold (fade up)
    z_signal = np.where(z >= threshold, 1, np.where(z <= -threshold, -1, 0))
    # jpy_macro_allowed = -pair_sign * z_signal
    #   JPY overbought + JPY-quote pair (neg corr) -> +1 (long, pair rises as JPY weakens)
    #   JPY oversold   + JPY-quote pair (neg corr) -> -1 (short, pair falls as JPY strengthens)
    jpy["jpy_macro_allowed"] = (-pair_sign * z_signal).astype(int)

    # ------------------------------------------------------------------
    # 5. Merge onto intraday data by date (preserves df index)
    # ------------------------------------------------------------------
    jpy_signal = jpy[["Date", "jpy_z_score", "jpy_macro_allowed"]].copy()
    jpy_signal = jpy_signal.rename(columns={"Date": "_merge_date"})
    macro_map = jpy_signal.set_index("_merge_date")["jpy_macro_allowed"]
    zscore_map = jpy_signal.set_index("_merge_date")["jpy_z_score"]

    merge_dates = df_dates.dt.normalize()
    df["jpy_z_score"] = merge_dates.map(zscore_map).values
    df["jpy_macro_allowed"] = merge_dates.map(macro_map).fillna(0).astype(int).values

    return df
