"""
Rolling-window analysis.
Artifact-only: consumes equity_curve.csv and deployable_trade_log.csv.
"""

import pandas as pd
import numpy as np


def rolling_window(
    eq_df: pd.DataFrame,
    tr_df: pd.DataFrame,
    window_days: int = 365,
    step_days: int = 30,
) -> pd.DataFrame:
    """Compute rolling return, max DD, and trade count over sliding windows."""
    eq = eq_df.copy()
    eq["timestamp"] = pd.to_datetime(eq["timestamp"])
    eq = eq.set_index("timestamp")
    eq = eq[~eq.index.duplicated(keep="last")]
    eq = eq.sort_index()
    daily = eq["equity"].resample("D").last().ffill()

    tr = tr_df.copy()
    tr["exit_timestamp"] = pd.to_datetime(tr["exit_timestamp"])

    start = daily.index[0]
    end = daily.index[-1]
    rows = []

    current = start
    while current + pd.Timedelta(days=window_days) <= end:
        w_end = current + pd.Timedelta(days=window_days)
        w_eq = daily.loc[current:w_end]

        if len(w_eq) < 2:
            current += pd.Timedelta(days=step_days)
            continue

        ret = (w_eq.iloc[-1] / w_eq.iloc[0] - 1) * 100
        peak = w_eq.cummax()
        dd = ((peak - w_eq) / peak * 100).max()

        trades_in = tr[
            (tr["exit_timestamp"] >= current) & (tr["exit_timestamp"] <= w_end)
        ]
        rows.append(
            {
                "start": current,
                "end": w_end,
                "return_pct": ret,
                "max_dd_pct": dd,
                "trade_count": len(trades_in),
            }
        )
        current += pd.Timedelta(days=step_days)

    return pd.DataFrame(rows)


def classify_stability(windows_df: pd.DataFrame) -> dict:
    """Classify rolling-window stability."""
    if windows_df.empty:
        return {"negative_windows": 0, "dd_over_15": 0, "clustering": "N/A"}

    ret = windows_df["return_pct"]
    dd = windows_df["max_dd_pct"]

    neg = windows_df[ret < 0]
    if len(neg) == 0:
        clustering = "N/A (No negative windows)"
    elif len(neg) == 1:
        clustering = "ISOLATED (Only 1)"
    else:
        neg_sorted = neg.sort_values("start")
        diffs = neg_sorted["start"].diff().dt.days
        clustering = "CLUSTERED" if (diffs <= 60).any() else "ISOLATED"

    return {
        "total_windows": len(windows_df),
        "negative_windows": int((ret < 0).sum()),
        "ret_under_minus_10": int((ret < -10).sum()),
        "dd_over_15": int((dd > 15).sum()),
        "dd_over_20": int((dd > 20).sum()),
        "worst_return": float(ret.min()),
        "worst_dd": float(dd.max()),
        "mean_return": float(ret.mean()),
        "mean_dd": float(dd.mean()),
        "clustering": clustering,
    }
