"""
Robustness tests — tail, directional, symbol isolation, regime splits.
Artifact-only: consumes deployable_trade_log.csv.
"""

import numpy as np
import pandas as pd


def tail_contribution(tr_df: pd.DataFrame) -> dict:
    """Rank trade PnL contribution by top 1, 5, 1%, 5%."""
    sorted_df = tr_df.sort_values("pnl_usd", ascending=False).reset_index(drop=True)
    total_pnl = sorted_df["pnl_usd"].sum()
    n = len(sorted_df)

    n1p = max(1, int(n * 0.01))
    n5p = max(1, int(n * 0.05))

    if total_pnl == 0:
        return {"top_1": 0, "top_5": 0, "top_1pct": 0, "top_5pct": 0}

    return {
        "top_1": sorted_df.head(1)["pnl_usd"].sum() / total_pnl,
        "top_5": sorted_df.head(5)["pnl_usd"].sum() / total_pnl,
        "top_1pct": sorted_df.head(n1p)["pnl_usd"].sum() / total_pnl,
        "top_5pct": sorted_df.head(n5p)["pnl_usd"].sum() / total_pnl,
        "total_pnl": total_pnl,
        "n_1pct": n1p,
        "n_5pct": n5p,
    }


def tail_removal(
    tr_df: pd.DataFrame,
    pct_cutoff: float = 0.05,
    start_cap: float = 10_000,
    sim_years: float | None = None,
) -> dict:
    """Remove top N% trades by PnL; recalculate CAGR degradation."""
    sorted_df = tr_df.sort_values("pnl_usd", ascending=False).reset_index(drop=True)
    n_remove = max(1, int(len(sorted_df) * pct_cutoff))

    orig_pnl = sorted_df["pnl_usd"].sum()
    rem_pnl = sorted_df.iloc[n_remove:]["pnl_usd"].sum()

    if sim_years is None:
        ts = pd.to_datetime(sorted_df["entry_timestamp"])
        sim_years = max((ts.max() - ts.min()).days / 365.25, 1.0)

    orig_eq = start_cap + orig_pnl
    new_eq = start_cap + rem_pnl

    orig_cagr = (orig_eq / start_cap) ** (1 / sim_years) - 1 if orig_eq > 0 else -1
    new_cagr = (new_eq / start_cap) ** (1 / sim_years) - 1 if new_eq > 0 else -1

    return {
        "removed_count": n_remove,
        "original_cagr": orig_cagr,
        "new_cagr": new_cagr,
        "original_equity": orig_eq,
        "new_equity": new_eq,
        "degradation_pct": (orig_cagr - new_cagr) / abs(orig_cagr) * 100 if abs(orig_cagr) > 1e-6 else 0.0,
    }


def directional_removal(tr_df: pd.DataFrame) -> dict:
    """Remove top 20 longs, top 20 shorts, and both — measure PF residual."""

    def _pf(pnls: pd.Series) -> float:
        wins = pnls[pnls > 0].sum()
        losses = abs(pnls[pnls < 0].sum())
        return wins / losses if losses > 0 else 999.0

    base_pf = _pf(tr_df["pnl_usd"])

    longs = tr_df[tr_df["direction"] == 1].sort_values("pnl_usd", ascending=False)
    shorts = tr_df[tr_df["direction"] == -1].sort_values("pnl_usd", ascending=False)

    no_long20 = tr_df.drop(longs.head(20).index) if len(longs) >= 20 else tr_df
    no_short20 = tr_df.drop(shorts.head(20).index) if len(shorts) >= 20 else tr_df

    drop_both = set()
    if len(longs) >= 20:
        drop_both |= set(longs.head(20).index)
    if len(shorts) >= 20:
        drop_both |= set(shorts.head(20).index)
    no_both = tr_df.drop(list(drop_both)) if drop_both else tr_df

    return {
        "baseline_pf": base_pf,
        "no_long20_pf": _pf(no_long20["pnl_usd"]),
        "no_short20_pf": _pf(no_short20["pnl_usd"]),
        "no_both_pf": _pf(no_both["pnl_usd"]),
        "n_longs": len(longs),
        "n_shorts": len(shorts),
    }


def symbol_isolation(tr_df: pd.DataFrame, start_cap: float = 10_000) -> list[dict]:
    """Remove one symbol at a time; report CAGR and DD impact."""
    from tools.utils.research.simulators import simulate_percent_path

    symbols = sorted(tr_df["symbol"].unique())
    results = []

    for sym in symbols:
        subset = tr_df[tr_df["symbol"] != sym].reset_index(drop=True)
        if subset.empty:
            continue
        res = simulate_percent_path(subset, start_cap)
        res["removed_symbol"] = sym
        res["remaining_trades"] = len(subset)
        results.append(res)

    return results


def early_late_split(tr_df: pd.DataFrame, start_cap: float = 10_000) -> dict:
    """Split trades at midpoint; compare CAGR and win rates."""
    from tools.utils.research.simulators import simulate_percent_path

    mid = len(tr_df) // 2
    first_half = tr_df.iloc[:mid].reset_index(drop=True)
    second_half = tr_df.iloc[mid:].reset_index(drop=True)

    r1 = simulate_percent_path(first_half, start_cap)
    r2 = simulate_percent_path(second_half, start_cap)

    r1["win_rate"] = (first_half["pnl_usd"] > 0).mean() * 100
    r2["win_rate"] = (second_half["pnl_usd"] > 0).mean() * 100
    r1["trade_count"] = len(first_half)
    r2["trade_count"] = len(second_half)

    return {"first_half": r1, "second_half": r2}
