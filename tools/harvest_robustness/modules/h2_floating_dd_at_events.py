"""h2_floating_dd_at_events.py -- quick lower-bound on intra-bar floating DD.

The DRY_RUN_VAULT/.../recycle_events.jsonl files carry per-event snapshots
of basket state including `floating_total` (floating PnL just before the
recycle action) and `equity_before` (realized + floating).

This gives the floating PnL AT EVENT TIMES. The true intra-bar Max DD between
events will be at least this value (lower bound) and likely worse. This script
gives the quick lower-bound estimate.

Output: per-basket worst floating-DD at any event timestamp.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from config.path_authority import DRY_RUN_VAULT
VAULT = DRY_RUN_VAULT / "baskets"
STAKE = 1000.0

BASKETS = {
    "B1 EUR+JPY": "90_PORT_H2_5M_RECYCLE_S03_V1_P00",
    "AUD+JPY":     "90_PORT_H2_5M_RECYCLE_S08_V1_P00",
    "GBP+JPY":     "90_PORT_H2_5M_RECYCLE_S08_V1_P01",
    "B2 AUD+CAD":  "90_PORT_H2_5M_RECYCLE_S05_V1_P04",
    "GBP+CAD":     "90_PORT_H2_5M_RECYCLE_S08_V1_P04",
    "EUR+CAD":     "90_PORT_H2_5M_RECYCLE_S08_V1_P03",
}


def basket_at_event_metrics(directive_id: str) -> dict:
    p = VAULT / directive_id / "H2" / "recycle_events.jsonl"
    if not p.exists():
        return {"err": f"missing {p}"}
    events = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    if not events:
        return {"err": "no events"}
    # floating_total at each event
    floats = [(e["bar_ts"], e["floating_total"], e["equity_before"], e["realized_total"]) for e in events]
    worst_floating = min(f[1] for f in floats)
    worst_idx = [i for i, f in enumerate(floats) if f[1] == worst_floating][0]
    worst_event = floats[worst_idx]
    # Equity at worst floating moment
    worst_equity = worst_event[2]
    starting = STAKE
    equity_dd_usd = starting - worst_equity if worst_equity < starting else 0
    # also track peak equity prior to worst event for a more accurate DD
    peak_so_far = max([STAKE] + [e[2] for e in floats[:worst_idx + 1]])
    dd_from_peak = peak_so_far - worst_equity
    return {
        "events": len(floats),
        "worst_floating_at_event_usd": worst_floating,
        "worst_event_ts": worst_event[0],
        "equity_at_worst_event": worst_equity,
        "peak_equity_up_to_worst": peak_so_far,
        "dd_from_peak_usd": dd_from_peak,
        "dd_from_peak_pct": dd_from_peak / peak_so_far * 100 if peak_so_far > 0 else 0,
        "dd_from_stake_pct": (STAKE - worst_equity) / STAKE * 100 if worst_equity < STAKE else 0,
    }


def main() -> int:
    print()
    print("AT-EVENT floating PnL snapshots (lower bound on intra-bar floating DD)")
    print("Worst floating_total recorded at any recycle event")
    print("=" * 130)
    print(f"{'Basket':18s} {'Events':>6s}  {'Worst Floating ($)':>18s}  {'Equity@worst ($)':>16s}  {'Peak-equity ($)':>16s}  {'DD from peak ($)':>17s}  {'DD%':>7s}  Worst-event timestamp")
    print("-" * 130)
    for label, did in BASKETS.items():
        m = basket_at_event_metrics(did)
        if "err" in m:
            print(f"{label:18s} {m['err']}")
            continue
        print(
            f"{label:18s} {m['events']:>6d}  "
            f"{m['worst_floating_at_event_usd']:>18.2f}  "
            f"{m['equity_at_worst_event']:>16.2f}  "
            f"{m['peak_equity_up_to_worst']:>16.2f}  "
            f"{m['dd_from_peak_usd']:>17.2f}  "
            f"{m['dd_from_peak_pct']:>6.2f}%  "
            f"{m['worst_event_ts']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
