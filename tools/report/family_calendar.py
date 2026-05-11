"""Calendar bucketing helpers for trade-level analysis.

Wrapper-first per FAMILY_REPORT_IMPLEMENTATION_PLAN.md Rule 4: this module
duplicates the inline yearwise/monthly logic at
``tools/robustness/runner.py:159-183`` rather than extracting it. The
original implementation stays untouched in the first release.

Function bodies are byte-equivalent to the inline copy in `runner.py`. Unit
tests pin both implementations against the same fixture inputs so any
future divergence is detectable.
"""

from __future__ import annotations

import pandas as pd


def yearwise_pnl(tr_df: pd.DataFrame) -> dict:
    """Per-year trade count, net PnL, win rate, avg PnL.

    Returns ``{ "2024": {trades, net_pnl, win_rate, avg_pnl}, "2025": {...}, ... }``.
    Mirrors ``tools/robustness/runner.py:159-177``.
    """
    if tr_df is None or len(tr_df) == 0:
        return {}
    if "exit_timestamp" not in tr_df.columns or "pnl_usd" not in tr_df.columns:
        return {}
    tr_tmp = tr_df.copy()
    tr_tmp["exit_timestamp"] = pd.to_datetime(tr_tmp["exit_timestamp"], errors="coerce")
    tr_tmp = tr_tmp.dropna(subset=["exit_timestamp"])
    tr_tmp["year"] = tr_tmp["exit_timestamp"].dt.year

    out: dict[str, dict] = {}
    for yr, grp in tr_tmp.groupby("year"):
        n_yr = len(grp)
        net_yr = float(grp["pnl_usd"].sum())
        wr_yr = float((grp["pnl_usd"] > 0).mean() * 100) if n_yr > 0 else 0.0
        avg_yr = float(grp["pnl_usd"].mean()) if n_yr > 0 else 0.0
        out[str(int(yr))] = {
            "trades": n_yr,
            "net_pnl": net_yr,
            "win_rate": wr_yr,
            "avg_pnl": avg_yr,
        }
    return out


def monthly_heatmap(tr_df: pd.DataFrame) -> dict:
    """Year × month pivot of summed PnL.

    Returns ``{ "2024": {"1": 12.34, "2": 56.78, ...}, "2025": {...}, ... }``.
    Mirrors ``tools/robustness/runner.py:179-183``.
    """
    if tr_df is None or len(tr_df) == 0:
        return {}
    if "exit_timestamp" not in tr_df.columns or "pnl_usd" not in tr_df.columns:
        return {}
    tr_tmp = tr_df.copy()
    tr_tmp["exit_timestamp"] = pd.to_datetime(tr_tmp["exit_timestamp"], errors="coerce")
    tr_tmp = tr_tmp.dropna(subset=["exit_timestamp"])
    tr_tmp["year"] = tr_tmp["exit_timestamp"].dt.year
    tr_tmp["month"] = tr_tmp["exit_timestamp"].dt.month

    if len(tr_tmp) == 0:
        return {}
    pivot = tr_tmp.pivot_table(
        values="pnl_usd", index="year", columns="month",
        aggfunc="sum", fill_value=0,
    )
    out: dict[str, dict] = {}
    for yr in pivot.index:
        out[str(int(yr))] = {str(int(m)): float(pivot.loc[yr, m]) for m in pivot.columns}
    return out
