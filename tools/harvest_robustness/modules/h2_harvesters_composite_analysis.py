"""h2_harvesters_composite_analysis.py — composite ranking from parquet ledger.

[REWRITTEN 2026-05-16] Reads 1.3.0-basket per-bar parquet ledgers and
enumerates all 2-of-N and 3-of-N composite combinations across the
champion set, ranked by capital efficiency (PnL / Max DD).

Previous implementation used `results_tradelevel.csv` realized equity and
the legacy reload+replay reconstruction for intra-bar DD. Both are now
obsolete — parquet's `equity_total_usd` column is the authoritative
per-bar equity (stake + realized + floating, internally consistent).

Inputs: parquet files at
    TradeScan_State/backtests/<directive_id>_H2/raw/results_basket_per_bar.parquet

Outputs: per-composite Max DD + capital-efficiency ranking to stdout.
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from tools.harvest_robustness.modules.h2_intrabar_floating_dd import (
    BASKETS, STAKE_PER_BASKET, basket_dd_metrics, compose_equity, load_basket_equity,
)


def main() -> int:
    # Load all available champions
    basket_equity: dict[str, pd.Series] = {}
    pair_names: dict[str, str] = {}
    for label, (directive_id, pair_name) in BASKETS.items():
        try:
            basket_equity[label] = load_basket_equity(directive_id)
            pair_names[label] = pair_name
        except FileNotFoundError:
            continue

    if len(basket_equity) < 2:
        print(f"[SKIP] Need >= 2 baskets with parquet ledgers; got {len(basket_equity)}.")
        return 1

    available = sorted(basket_equity.keys())
    print(f"Available champions with parquet: {available}\n")

    # Singles + all pair combos + triple
    rows: list[dict] = []
    for label in available:
        eq = basket_equity[label]
        m = basket_dd_metrics(eq, STAKE_PER_BASKET, label)
        rows.append({
            "name":         f"{label} ({pair_names[label]})",
            "members":      1,
            "stake":        STAKE_PER_BASKET,
            "final_eq":     m["final_eq"],
            "net_pnl":      m["net_pnl"],
            "net_pnl_pct":  m["net_pnl_pct"],
            "max_dd_usd":   m["max_dd_usd"],
            "dd_pct_stake": m["max_dd_pct_of_stake"],
            "return_dd":    m["net_pnl"] / m["max_dd_usd"] if m["max_dd_usd"] > 0 else float("inf"),
        })

    for k in (2, 3):
        if len(available) < k:
            continue
        for combo in combinations(available, k):
            comp_eq = compose_equity(basket_equity, list(combo))
            stake = STAKE_PER_BASKET * len(combo)
            m = basket_dd_metrics(comp_eq, stake, "+".join(combo))
            rows.append({
                "name":         "+".join(combo),
                "members":      len(combo),
                "stake":        stake,
                "final_eq":     m["final_eq"],
                "net_pnl":      m["net_pnl"],
                "net_pnl_pct":  m["net_pnl_pct"],
                "max_dd_usd":   m["max_dd_usd"],
                "dd_pct_stake": m["max_dd_pct_of_stake"],
                "return_dd":    m["net_pnl"] / m["max_dd_usd"] if m["max_dd_usd"] > 0 else float("inf"),
            })

    print("=" * 110)
    print("COMPOSITE RANKING -- sorted by return/DD (capital efficiency)")
    print("=" * 110)
    print(f"{'Rank':>4s}  {'Composite':18s} {'N':>2s}  {'Stake':>7s}  "
          f"{'Final eq':>9s}  {'Net PnL':>9s}  {'PnL%':>6s}  "
          f"{'MaxDD $':>9s}  {'DD%stake':>8s}  {'PnL/DD':>7s}")
    print("-" * 110)
    rows.sort(key=lambda r: -r["return_dd"])
    for i, r in enumerate(rows, 1):
        print(
            f"{i:>4d}  {r['name']:18s} {r['members']:>2d}  ${r['stake']:>6.0f}  "
            f"${r['final_eq']:>8.2f}  ${r['net_pnl']:>+8.2f}  "
            f"{r['net_pnl_pct']:>+5.1f}%  ${r['max_dd_usd']:>8.2f}  "
            f"{r['dd_pct_stake']:>7.2f}%  {r['return_dd']:>6.2f}"
        )

    print()
    print("=" * 110)
    print("COMPOSITE RANKING -- sorted by DD%stake (lowest first; capital safety)")
    print("=" * 110)
    print(f"{'Rank':>4s}  {'Composite':18s} {'N':>2s}  {'DD%stake':>8s}  "
          f"{'MaxDD $':>9s}  {'Net PnL':>9s}  {'PnL%':>6s}  {'PnL/DD':>7s}")
    print("-" * 110)
    rows_by_dd = sorted(rows, key=lambda r: r["dd_pct_stake"])
    for i, r in enumerate(rows_by_dd, 1):
        print(
            f"{i:>4d}  {r['name']:18s} {r['members']:>2d}  {r['dd_pct_stake']:>7.2f}%  "
            f"${r['max_dd_usd']:>8.2f}  ${r['net_pnl']:>+8.2f}  "
            f"{r['net_pnl_pct']:>+5.1f}%  {r['return_dd']:>6.2f}"
        )

    print()
    print("Notes:")
    print("  - 'MaxDD $' = peak intra-bar floating drawdown computed on the composite equity series.")
    print("  - 'DD%stake' = MaxDD / total stake; operator-facing 'how much of nominal capital floats underwater'.")
    print("  - 'PnL/DD' = net PnL per dollar of DD; capital efficiency ratio.")
    print("  - All numbers derived from the spec-correct 1.3.0-basket parquet ledger; no reload+replay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
