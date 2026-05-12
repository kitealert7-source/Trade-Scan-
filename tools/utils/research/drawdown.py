"""
Drawdown cluster identification and diagnostics.
Artifact-only: consumes equity_curve.csv and deployable_trade_log.csv.
"""

import pandas as pd
import numpy as np


def identify_dd_clusters(eq_df: pd.DataFrame, top_n: int = 3) -> list[dict]:
    """Find the top-N deepest drawdown periods from the equity curve."""
    eq = eq_df.copy()
    eq["timestamp"] = pd.to_datetime(eq["timestamp"])
    eq = eq.set_index("timestamp")
    eq = eq[~eq.index.duplicated(keep="last")]
    daily = eq["equity"].resample("D").last().ffill()

    peak = daily.cummax()
    dd_pct = (peak - daily) / peak * 100

    dd_df = pd.DataFrame({"equity": daily, "peak": peak, "dd_pct": dd_pct})
    dd_df["is_peak"] = dd_df["equity"] == dd_df["peak"]

    periods = []
    in_dd = False
    start_dt = None
    max_dd = 0.0
    trough_dt = None

    for dt, row in dd_df.iterrows():
        if row["is_peak"]:
            if in_dd:
                periods.append(
                    {
                        "start_date": start_dt,
                        "trough_date": trough_dt,
                        "recovery_date": dt,
                        "max_dd_pct": max_dd,
                        "duration_days": (dt - start_dt).days,
                    }
                )
                in_dd = False
        else:
            if not in_dd:
                start_dt = dt
                in_dd = True
                max_dd = row["dd_pct"]
                trough_dt = dt
            elif row["dd_pct"] > max_dd:
                max_dd = row["dd_pct"]
                trough_dt = dt

    if in_dd:
        periods.append(
            {
                "start_date": start_dt,
                "trough_date": trough_dt,
                "recovery_date": pd.NaT,
                "max_dd_pct": max_dd,
                "duration_days": (dd_df.index[-1] - start_dt).days,
            }
        )

    periods.sort(key=lambda x: x["max_dd_pct"], reverse=True)
    return periods[:top_n]


def analyze_dd_exposure(tr_df: pd.DataFrame, cluster: dict) -> dict:
    """Analyze portfolio exposure during a drawdown cluster."""
    tr = tr_df.copy()
    tr["entry_timestamp"] = pd.to_datetime(tr["entry_timestamp"])
    tr["exit_timestamp"] = pd.to_datetime(tr["exit_timestamp"])

    start = cluster["start_date"]
    trough = cluster["trough_date"]

    # Trades open during the plunge
    open_mask = (tr["entry_timestamp"] <= trough) & (tr["exit_timestamp"] >= start)
    open_trades = tr[open_mask]

    n = len(open_trades)
    if n == 0:
        return {
            "total_trades": 0,
            "pct_long": 0,
            "pct_short": 0,
            "symbol_concentration_top2": 0,
        }

    pct_long = (open_trades["direction"] == 1).sum() / n * 100
    pct_short = (open_trades["direction"] == -1).sum() / n * 100

    sym_counts = open_trades["symbol"].value_counts()
    top2 = sym_counts.head(2).sum() / n * 100 if n > 0 else 0

    return {
        "total_trades": n,
        "pct_long": pct_long,
        "pct_short": pct_short,
        "symbol_concentration_top2": top2,
    }


def analyze_dd_trade_behavior(tr_df: pd.DataFrame, cluster: dict) -> dict:
    """Analyze trade outcomes during a drawdown cluster."""
    tr = tr_df.copy()
    tr["exit_timestamp"] = pd.to_datetime(tr["exit_timestamp"])

    start = cluster["start_date"]
    trough = cluster["trough_date"]

    closed = tr[(tr["exit_timestamp"] >= start) & (tr["exit_timestamp"] <= trough)]

    n = len(closed)
    if n == 0:
        return {"trades_closed": 0}

    win_rate = (closed["pnl_usd"] > 0).sum() / n * 100
    avg_pnl = closed["pnl_usd"].mean()
    total_pnl = closed["pnl_usd"].sum()

    # loss streak
    streaks = (closed["pnl_usd"] < 0).astype(int)
    groups = streaks.groupby((streaks != streaks.shift()).cumsum())
    max_loss_streak = int(groups.sum().max()) if not groups.sum().empty else 0

    return {
        "trades_closed": n,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "max_loss_streak": max_loss_streak,
    }
