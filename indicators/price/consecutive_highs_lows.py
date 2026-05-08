import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "consecutive_highs_lows_breakout"
PIVOT_SOURCE = "none"


def consecutive_highs_lows(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Detects n consecutive higher highs (hh3) or lower lows (ll3) over an
    n+1 bar window, and computes the structural stop levels for each direction.

    Outputs added to df (in-place):
        hh3       (bool)  — True when high[0] > high[1] > ... > high[n]
        ll3       (bool)  — True when low[0]  < low[1]  < ... < low[n]
        hh3_sl    (float) — min(low[0..n]):  structural long stop (lowest low in window)
        ll3_sl    (float) — max(high[0..n]): structural short stop (highest high in window)

    Default n=3, giving a 4-bar window (current + 3 lookback bars).
    """
    n = int((params or {}).get("n", 3))

    highs = df["high"]
    lows = df["low"]

    # n consecutive higher highs: high[i] > high[i+1] for i in 0..n-1
    hh = pd.Series(True, index=df.index)
    for i in range(1, n + 1):
        hh = hh & (highs.shift(i - 1) > highs.shift(i))

    # n consecutive lower lows: low[i] < low[i+1] for i in 0..n-1
    ll = pd.Series(True, index=df.index)
    for i in range(1, n + 1):
        ll = ll & (lows.shift(i - 1) < lows.shift(i))

    # Structural stop = extreme of the n+1 bar window
    low_window = pd.concat([lows.shift(i) for i in range(n + 1)], axis=1)
    high_window = pd.concat([highs.shift(i) for i in range(n + 1)], axis=1)

    df["hh3"] = hh.fillna(False)
    df["ll3"] = ll.fillna(False)
    df["hh3_sl"] = low_window.min(axis=1)   # long structural stop
    df["ll3_sl"] = high_window.max(axis=1)  # short structural stop

    return df


apply = consecutive_highs_lows
