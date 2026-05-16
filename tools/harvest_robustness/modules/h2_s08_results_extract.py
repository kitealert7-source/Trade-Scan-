"""h2_s08_results_extract.py -- aggregate S08 sweep results into ranked table.

For each S08 directive (plus B1 + B2 baselines), extract:
  - trades count
  - recycle events  (rows with bars_held == 0)
  - net PnL ($)
  - final equity ($)
  - Max DD ($, %)
  - days_to_harvest (if final_eq >= $2000, days from first entry to last exit)
  - PF (profit factor)
Then sort by net PnL descending and print as markdown table.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # modules/ -> harvest_robustness/ -> tools/ -> repo
from config.path_authority import TRADE_SCAN_STATE
BACKTESTS = TRADE_SCAN_STATE / "backtests"

STAKE = 1000.0
HARVEST_TARGET = 2000.0  # final equity >= this means harvested

# (label, directive_id, pair-pair shorthand)
ROWS = [
    ("B1*",   "90_PORT_H2_5M_RECYCLE_S03_V1_P00", "EUR+JPY"),
    ("B2*",   "90_PORT_H2_5M_RECYCLE_S05_V1_P04", "AUD+CAD"),
    ("S08_P00", "90_PORT_H2_5M_RECYCLE_S08_V1_P00", "AUD+JPY"),
    ("S08_P01", "90_PORT_H2_5M_RECYCLE_S08_V1_P01", "GBP+JPY"),
    ("S08_P02", "90_PORT_H2_5M_RECYCLE_S08_V1_P02", "NZD+JPY"),
    ("S08_P03", "90_PORT_H2_5M_RECYCLE_S08_V1_P03", "EUR+CAD"),
    ("S08_P04", "90_PORT_H2_5M_RECYCLE_S08_V1_P04", "GBP+CAD"),
    ("S08_P05", "90_PORT_H2_5M_RECYCLE_S08_V1_P05", "NZD+CAD"),
    ("S08_P06", "90_PORT_H2_5M_RECYCLE_S08_V1_P06", "EUR+CHF"),
    ("S08_P07", "90_PORT_H2_5M_RECYCLE_S08_V1_P07", "AUD+CHF"),
    ("S08_P08", "90_PORT_H2_5M_RECYCLE_S08_V1_P08", "GBP+CHF"),
    ("S08_P09", "90_PORT_H2_5M_RECYCLE_S08_V1_P09", "NZD+CHF"),
]


def metrics(directive_id: str) -> dict:
    tlp = BACKTESTS / f"{directive_id}_H2" / "raw" / "results_tradelevel.csv"
    if not tlp.exists():
        return {"err": "tradelevel missing"}
    df = pd.read_csv(tlp)
    if df.empty:
        return {"err": "empty"}
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"])
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"])
    df = df.sort_values("entry_timestamp").reset_index(drop=True)
    n_trades = len(df)
    # Recycle event = bars_held == 0 (intra-bar realize+grow event)
    n_recycle = int((df["bars_held"] == 0).sum()) if "bars_held" in df.columns else 0
    pnl_total = float(df["pnl_usd"].sum())
    df["realized_eq"] = STAKE + df["pnl_usd"].cumsum()
    final_eq = float(df["realized_eq"].iloc[-1])
    peak = df["realized_eq"].cummax()
    drawdown = df["realized_eq"] - peak
    max_dd_usd = float(-drawdown.min())
    max_dd_pct = max_dd_usd / float(peak.max()) * 100 if peak.max() > 0 else 0.0
    gross_win = float(df.loc[df["pnl_usd"] > 0, "pnl_usd"].sum())
    gross_loss = float(-df.loc[df["pnl_usd"] < 0, "pnl_usd"].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    # Days = first entry -> last exit (basket lifetime)
    elapsed_days = (df["exit_timestamp"].iloc[-1] - df["entry_timestamp"].iloc[0]).days
    # Harvested if final equity >= $2000
    harvested = final_eq >= HARVEST_TARGET
    return {
        "trades": n_trades,
        "recycles": n_recycle,
        "pnl_usd": pnl_total,
        "pnl_pct": pnl_total / STAKE * 100,
        "final_eq": final_eq,
        "max_dd_usd": max_dd_usd,
        "max_dd_pct": max_dd_pct,
        "pf": pf,
        "harvested": harvested,
        "elapsed_days": elapsed_days,
    }


def fmt(m: dict) -> str:
    if "err" in m:
        return f" {m['err']}"
    pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
    dh = f"HARVEST @ {m['elapsed_days']}d" if m["harvested"] else f"no-harvest / {m['elapsed_days']}d"
    return (
        f"trd={m['trades']:3d} rec={m['recycles']:3d}  PnL=${m['pnl_usd']:7.2f} ({m['pnl_pct']:+6.1f}%)  "
        f"DD=${m['max_dd_usd']:6.2f}/{m['max_dd_pct']:6.2f}%  PF={pf:>6s}  {dh}"
    )


def main() -> int:
    print("\nS08 USD-anchored matrix -- sweep results")
    print("=" * 120)
    results = []
    for label, did, pair in ROWS:
        m = metrics(did)
        results.append((label, did, pair, m))
        print(f"{label:8s}  {pair:8s}  {fmt(m)}")
    # Ranked by PnL descending
    print("\n\nRanked by PnL descending:")
    print("=" * 120)
    valid = [(l, d, p, m) for (l, d, p, m) in results if "err" not in m]
    ranked = sorted(valid, key=lambda r: -r[3]["pnl_usd"])
    for label, did, pair, m in ranked:
        print(f"{label:8s}  {pair:8s}  {fmt(m)}")
    # Markdown table
    print("\n\nMarkdown table (for FX_BASKET_RECYCLE_RESEARCH.md):")
    print("=" * 120)
    print("| Label | Pair-pair | Trades | Recycles | PnL ($) | PnL (%) | Max DD ($) | Max DD (%) | PF | Outcome |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, did, pair, m in ranked:
        if "err" in m:
            continue
        pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        outcome = f"HARVEST @ {m['elapsed_days']}d" if m["harvested"] else f"no harvest / {m['elapsed_days']}d"
        print(f"| {label} | {pair} | {m['trades']} | {m['recycles']} | {m['pnl_usd']:.2f} | {m['pnl_pct']:+.1f}% | {m['max_dd_usd']:.2f} | {m['max_dd_pct']:.3f}% | {pf} | {outcome} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
