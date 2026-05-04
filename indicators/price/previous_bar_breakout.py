import pandas as pd

def apply(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """In-place mutator: adds prev_high / prev_low / breakout_up_close /
    breakout_down_close to the caller's df, returns the same object.
    See tests/indicator/test_inplace_contract.py.
    """
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)

    df["breakout_up_close"] = df["close"] > df["prev_high"]
    df["breakout_down_close"] = df["close"] < df["prev_low"]

    return df