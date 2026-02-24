# indicators/price/candle_state.py

import pandas as pd

def apply(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Adds:
        - is_green (bool)
        - is_red (bool)
        - green_streak (int)
        - red_streak (int)
    """

    df = df.copy()

    df["is_green"] = df["close"] > df["open"]
    df["is_red"] = df["close"] < df["open"]

    # Consecutive streak counters
    green_streak = []
    red_streak = []

    g_count = 0
    r_count = 0

    for is_g, is_r in zip(df["is_green"], df["is_red"]):
        if is_g:
            g_count += 1
        else:
            g_count = 0

        if is_r:
            r_count += 1
        else:
            r_count = 0

        green_streak.append(g_count)
        red_streak.append(r_count)

    df["green_streak"] = green_streak
    df["red_streak"] = red_streak

    return df