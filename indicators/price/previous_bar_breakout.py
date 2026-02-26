import pandas as pd

def apply(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    df = df.copy()

    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)

    df["breakout_up_close"] = df["close"] > df["prev_high"]
    df["breakout_down_close"] = df["close"] < df["prev_low"]

    return df