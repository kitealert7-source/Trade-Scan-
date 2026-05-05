import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "consecutive_close_streak"
PIVOT_SOURCE = "none"


def consecutive_closes(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Tracks consecutive lower/higher closes (close-to-close, strict inequality).

    Outputs:
        close_lower_streak  (int)  — bars where close < prev close, running count
        close_higher_streak (int)  — bars where close > prev close, running count
        p000 (bool) — True when close_lower_streak  >= n (default 3)
        p111 (bool) — True when close_higher_streak >= n (default 3)

    Equal closes reset both streaks (strict inequality).

    Mutates df in place (Stage-1 contract). Must not create or return a new DataFrame.
    """
    n = int((params or {}).get("n", 3))

    closes = df["close"].tolist()
    lower: list[int] = []
    higher: list[int] = []
    l_count = 0
    h_count = 0

    # GOVERNANCE: sequential by design — streak counting requires running state.
    for i, c in enumerate(closes):
        if i == 0:
            l_count = 0
            h_count = 0
        elif c < closes[i - 1]:
            l_count += 1
            h_count = 0
        elif c > closes[i - 1]:
            h_count += 1
            l_count = 0
        else:
            l_count = 0
            h_count = 0
        lower.append(l_count)
        higher.append(h_count)

    df["close_lower_streak"] = lower
    df["close_higher_streak"] = higher
    df["p000"] = df["close_lower_streak"] == n
    df["p111"] = df["close_higher_streak"] == n

    return df


apply = consecutive_closes
