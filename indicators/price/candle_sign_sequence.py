# indicators/price/candle_sign_sequence.py

import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "close_sign_run"
PIVOT_SOURCE = "none"


def apply(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Inter-bar close-sign sequence primitive.

    Adds:
        - bar_sign (int): +1 if close > prev_close, -1 if close < prev_close,
                          0 if equal or prev_close is NaN (warmup / ties).
        - run_len (int):  signed consecutive same-sign streak ending at this bar.
                          +N while sign stays +1, -N while sign stays -1,
                          resets to 0 on a doji (bar_sign == 0) or sign flip
                          before being set to +/-1.

    Pattern usage:
        run_len[i] <= -3  → close[i] < close[i-1] < close[i-2] < close[i-3]
                            (three consecutive lower closes ending at i)
        run_len[i] >=  3  → three consecutive higher closes ending at i

    Lookahead-safe (uses shift(1) only).
    Output Scale: bar_sign: -1/0/+1; run_len: signed int.
    """

    df = df.copy()

    prev_close = df["close"].shift(1)
    sign = (df["close"] > prev_close).astype(int) - (df["close"] < prev_close).astype(int)
    df["bar_sign"] = sign.astype(int)

    # GOVERNANCE: iterative by design (O(n)), no nested loops.
    # Signed run-length requires sequential state — cannot be vectorized.
    run_len = []
    current = 0
    for s in df["bar_sign"].to_numpy():
        if s > 0:
            current = current + 1 if current > 0 else 1
        elif s < 0:
            current = current - 1 if current < 0 else -1
        else:
            current = 0
        run_len.append(current)

    df["run_len"] = run_len
    return df
