"""h2_harvesters_composite_analysis.py -- compare parallel composites of harvester baskets.

Question (operator, 2026-05-16): does combining all 3 harvesting pairs (B1, AUD+JPY,
GBP+JPY) -- or any 2 of them -- smooth the equity curve, or worsen it?

Three harvesters (S08 sweep) all sit in the JPY column of the USD-anchored matrix:
  B1 (S03_P00):  EUR+JPY  -- 302d harvest, Max DD 0.55%, PF 72.92
  S08_P00:        AUD+JPY  -- 532d harvest, Max DD 0.54%, PF 62.45
  S08_P01:        GBP+JPY  -- 441d harvest, Max DD 20.12%, PF 3.49 (GBP tail risk)

Method: load each basket's tradelevel CSV, build unified time axis (union of
all event timestamps), forward-fill each basket's realized equity, sum across
baskets to get composite equity. Compute composite Max DD, Sharpe, Sortino,
combined days-to-finish.

For comparison: B1+B2 (original champion composite, 0.374% DD on $2k stake).

Note on the shared-JPY question: all three harvesters use USDJPY as their
USD-base leg. They share JPY directional exposure. The empirical question
is whether their recycle events still fire at sufficiently different times
to decorrelate the floating PnL paths, despite the shared JPY anchor.
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # modules/ -> harvest_robustness/ -> tools/ -> repo
from config.path_authority import TRADE_SCAN_STATE
BACKTESTS = TRADE_SCAN_STATE / "backtests"

STAKE_PER_BASKET = 1000.0

# (label, directive_id, short_name, category)
BASKETS = {
    "B1": ("90_PORT_H2_5M_RECYCLE_S03_V1_P00", "EUR+JPY", "harvester"),
    "AJ": ("90_PORT_H2_5M_RECYCLE_S08_V1_P00", "AUD+JPY", "harvester"),
    "GJ": ("90_PORT_H2_5M_RECYCLE_S08_V1_P01", "GBP+JPY", "harvester"),
    "B2": ("90_PORT_H2_5M_RECYCLE_S05_V1_P04", "AUD+CAD", "stabilizer"),
    "GC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P04", "GBP+CAD", "stabilizer"),
    "EC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P03", "EUR+CAD", "stabilizer"),
}


def load_trades(directive_id: str) -> pd.DataFrame:
    p = BACKTESTS / f"{directive_id}_H2" / "raw" / "results_tradelevel.csv"
    df = pd.read_csv(p)
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"])
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"])
    return df.sort_values("exit_timestamp").reset_index(drop=True)


def basket_realized_curve(trades: pd.DataFrame, stake: float) -> pd.Series:
    """Per-basket realized-PnL equity curve indexed by exit_timestamp."""
    t = trades.copy()
    t["realized_eq"] = stake + t["pnl_usd"].cumsum()
    t = t.set_index("exit_timestamp")
    return t["realized_eq"]


def composite_metrics(curves: dict[str, pd.Series], n_baskets: int) -> dict:
    """Build composite from list of per-basket curves."""
    stake_total = n_baskets * STAKE_PER_BASKET
    # Union of all event timestamps
    all_times = sorted({t for c in curves.values() for t in c.index})
    df = pd.DataFrame(index=pd.DatetimeIndex(all_times))
    for label, curve in curves.items():
        df[label] = curve.reindex(df.index, method="ffill").fillna(STAKE_PER_BASKET)
    df["composite"] = df.sum(axis=1)

    # Max DD on composite equity curve
    peak = df["composite"].cummax()
    drawdown = df["composite"] - peak
    max_dd_usd = float(-drawdown.min())
    max_dd_pct = max_dd_usd / float(peak.max()) * 100 if peak.max() > 0 else 0.0
    final_eq = float(df["composite"].iloc[-1])
    net_pnl = final_eq - stake_total
    days = (df.index[-1] - df.index[0]).days

    # Sharpe / Sortino on daily-resampled returns
    daily_eq = df["composite"].resample("1D").last().ffill()
    daily_ret = daily_eq.diff().dropna()
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252)
    else:
        sharpe = 0.0
    sortino_denom = daily_ret[daily_ret < 0].std()
    if sortino_denom and sortino_denom > 0:
        sortino = (daily_ret.mean() / sortino_denom) * np.sqrt(252)
    else:
        sortino = 0.0

    return {
        "stake": stake_total,
        "final_eq": final_eq,
        "net_pnl": net_pnl,
        "net_pnl_pct": net_pnl / stake_total * 100,
        "max_dd_usd": max_dd_usd,
        "max_dd_pct": max_dd_pct,
        "days": days,
        "sharpe": sharpe,
        "sortino": sortino,
        "dd_to_pnl_ratio": max_dd_usd / net_pnl if net_pnl > 0 else float("inf"),
    }


def fmt(label: str, m: dict, baskets: str) -> str:
    return (
        f"{label:30s}  "
        f"PnL=${m['net_pnl']:7.2f} ({m['net_pnl_pct']:+6.1f}%)  "
        f"DD=${m['max_dd_usd']:7.2f}/{m['max_dd_pct']:6.2f}%  "
        f"days={m['days']:4d}  "
        f"Sharpe={m['sharpe']:5.2f}  Sortino={m['sortino']:6.2f}  "
        f"DD/PnL={m['dd_to_pnl_ratio']:5.3f}  "
        f"[{baskets}]"
    )


def main() -> int:
    # Pre-load all curves
    curves = {}
    for k, (did, name, cat) in BASKETS.items():
        t = load_trades(did)
        curves[k] = basket_realized_curve(t, STAKE_PER_BASKET)
        print(f"loaded {k} ({name}): {len(t)} trades")

    print()
    print("=" * 138)
    print("COMPARISON: composites of harvester baskets (+ B2 reference for diversification baseline)")
    print("=" * 138)

    results = []

    # Singles
    for k in ["B1", "AJ", "GJ"]:
        m = composite_metrics({k: curves[k]}, 1)
        name = BASKETS[k][1]
        results.append((f"SINGLE {name}", m, name))

    # Pairs (harvester combinations)
    for c in combinations(["B1", "AJ", "GJ"], 2):
        sub = {k: curves[k] for k in c}
        m = composite_metrics(sub, len(c))
        name = " + ".join(BASKETS[k][1] for k in c)
        results.append((f"PAIR   {name}", m, name))

    # Triple
    sub = {k: curves[k] for k in ["B1", "AJ", "GJ"]}
    m = composite_metrics(sub, 3)
    name = "B1 + AUD+JPY + GBP+JPY"
    results.append((f"TRIPLE {name}", m, name))

    # Reference: original champion composite B1+B2
    sub = {k: curves[k] for k in ["B1", "B2"]}
    m = composite_metrics(sub, 2)
    results.append(("REF-CHAMPION B1+B2", m, "EUR+JPY + AUD+CAD"))

    # E1 — Triple harvester+harvester+stabilizer (skip GBP+JPY)
    sub = {k: curves[k] for k in ["B1", "AJ", "B2"]}
    m = composite_metrics(sub, 3)
    results.append(("E1 TRIPLE B1+AJ+B2", m, "EUR+JPY + AUD+JPY + AUD+CAD"))

    # E2 — Quad composite (2 harvesters + 2 stabilizers)
    sub = {k: curves[k] for k in ["B1", "AJ", "B2", "GC"]}
    m = composite_metrics(sub, 4)
    results.append(("E2 QUAD B1+AJ+B2+GC", m, "EUR+JPY + AUD+JPY + AUD+CAD + GBP+CAD"))

    # Bonus comparisons
    # Three stabilizers (no harvester, slow but maybe smoothest)
    sub = {k: curves[k] for k in ["B2", "GC", "EC"]}
    m = composite_metrics(sub, 3)
    results.append(("BONUS TRIPLE STAB B2+GC+EC", m, "AUD+CAD + GBP+CAD + EUR+CAD"))

    # B1 + B2 + GC — original champion + extra stabilizer
    sub = {k: curves[k] for k in ["B1", "B2", "GC"]}
    m = composite_metrics(sub, 3)
    results.append(("BONUS B1+B2+GC", m, "EUR+JPY + AUD+CAD + GBP+CAD"))

    # Print as-listed
    for label, m, name in results:
        print(fmt(label, m, name))

    # Ranked by DD/PnL ratio (lower = smoother)
    print()
    print("Ranked by DD-to-PnL ratio (lower = smoother equity curve):")
    print("=" * 138)
    valid = [r for r in results if r[1]["dd_to_pnl_ratio"] != float("inf")]
    for label, m, name in sorted(valid, key=lambda r: r[1]["dd_to_pnl_ratio"]):
        print(fmt(label, m, name))

    # Markdown table for research doc
    print()
    print("Markdown table (for FX_BASKET_RECYCLE_RESEARCH.md):")
    print("=" * 138)
    print("| Composite | Baskets | Stake | Net PnL ($) | Net PnL (%) | Max DD ($) | Max DD (%) | Days | Sharpe | Sortino | DD/PnL |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, m, name in results:
        print(
            f"| {label} | {name} | ${m['stake']:.0f} | "
            f"{m['net_pnl']:.2f} | {m['net_pnl_pct']:+.1f}% | "
            f"{m['max_dd_usd']:.2f} | {m['max_dd_pct']:.3f}% | "
            f"{m['days']} | {m['sharpe']:.2f} | {m['sortino']:.2f} | "
            f"{m['dd_to_pnl_ratio']:.3f} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
