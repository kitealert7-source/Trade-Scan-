"""h2_floating_dd_at_events.py -- at-recycle-event floating PnL stats from parquet.

[REWRITTEN 2026-05-16] Reads the 1.3.0-basket per-bar parquet ledger and
extracts the floating_total_usd at every recycle_executed bar. Useful for
understanding the trigger-USD distribution and the basket's floating
profile at the moment recycle decisions fire.

This is a SUBORDINATE diagnostic to h2_intrabar_floating_dd.py; the true
intra-bar Max DD comes from per-bar min over the full ledger (not just
event bars). This module surfaces the EVENT-time snapshot for context.

Inputs: parquet ledgers at TradeScan_State/backtests/<id>_H2/raw/.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.path_authority import TRADE_SCAN_STATE
from tools.harvest_robustness.modules.h2_intrabar_floating_dd import BASKETS, STAKE_PER_BASKET


def _parquet_path(directive_id: str) -> Path:
    return (
        TRADE_SCAN_STATE / "backtests" / f"{directive_id}_H2" / "raw" / "results_basket_per_bar.parquet"
    )


def main() -> int:
    print("=" * 100)
    print("AT-EVENT FLOATING PROFILE (recycle_executed bars only, from parquet)")
    print("=" * 100)
    print(f"{'Basket':6s} {'Pair':10s} {'Events':>6s}  {'AvgFloat':>9s}  {'MinFloat':>9s}  "
          f"{'MaxFloat':>9s}  {'OverallMinFloat':>16s}  {'EventVsOverall':>15s}")
    print("-" * 100)

    for label, (directive_id, pair) in BASKETS.items():
        p = _parquet_path(directive_id)
        if not p.exists():
            print(f"{label:6s} {pair:10s} SKIP -- no parquet at {p}")
            continue
        df = pd.read_parquet(p, columns=["floating_total_usd", "recycle_executed"])
        events = df[df["recycle_executed"]]
        if events.empty:
            print(f"{label:6s} {pair:10s} (no recycle_executed bars)")
            continue
        avg_f = float(events["floating_total_usd"].mean())
        min_f = float(events["floating_total_usd"].min())
        max_f = float(events["floating_total_usd"].max())
        overall_min = float(df["floating_total_usd"].min())
        # Gap: how much deeper does the basket go BETWEEN events vs at events?
        gap_pct = (overall_min - min_f) / overall_min * 100.0 if overall_min < 0 else 0.0
        print(
            f"{label:6s} {pair:10s} {len(events):>6d}  "
            f"${avg_f:>+8.2f}  ${min_f:>+8.2f}  ${max_f:>+8.2f}  "
            f"${overall_min:>+15.2f}  {gap_pct:>14.1f}%"
        )

    print()
    print("Notes:")
    print("  - 'AvgFloat'  = mean floating_total_usd across all recycle_executed bars.")
    print("    Values are post-recycle (winner already realized, lot mutations applied) per the 2026-05-16 emitter fix.")
    print("  - 'MinFloat / MaxFloat' = floating PnL range observed at recycle bars only.")
    print("  - 'OverallMinFloat'     = min floating across ALL bars (between events too).")
    print("  - 'EventVsOverall'      = how much deeper the worst between-event bar goes vs the worst event bar.")
    print("    A large gap means recycle events fire BEFORE the worst floating moment -- the rule's freeze gates")
    print("    let the basket float deeper between recycle invocations.")
    print("  - True intra-bar Max DD per basket: see section 4 (h2_intrabar_floating_dd).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
