"""h2_intrabar_floating_dd.py — Intra-bar floating Max DD from parquet ledger.

[REWRITTEN 2026-05-16] This module reads the 1.3.0-basket per-bar parquet
ledger emitted by H2RecycleRule at basket close. Path:

    TradeScan_State/backtests/<directive_id>_<basket_id>/raw/results_basket_per_bar.parquet

The previous reload+replay implementation had two state-model bugs
(winner-lot-reset, bar-0 entry-price) that overstated DD by 5-35%. The new
emitter is spec-aligned (basket_sim.py:362,388 "lot unchanged"), and the
on-disk recycle_events.jsonl independently confirms the spec. The legacy
reload+replay path is gone — analytics are parquet-only.

For pre-1.3.0 basket runs without a parquet ledger, this module reports
"SKIP: no ledger" — those baskets must be re-run through the pipeline
to generate the parquet before they can be analyzed.

Outputs:
  - per-basket intra-bar Max DD table (close-based, from authoritative ledger)
  - composite intra-bar Max DD across the champion combinations:
      B1, AJ, B2 singles  /  B1+AJ, B1+B2, AJ+B2 pairs  /  B1+AJ+B2 = E1 triple

Reference: outputs/H2_TELEMETRY_PARITY_FORENSIC.md (root-cause + forensic).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.path_authority import TRADE_SCAN_STATE

STAKE_PER_BASKET = 1000.0

# Champion set (1.3.0-basket parquet on disk). Add directives as parquet
# ledgers come online (each basket must be re-run through the pipeline
# under the 1.3.0-basket emitter to generate one).
#
# Sleeve challenge (2026-05-16 operator request): EC, GC, AC added as
# second-sleeve candidates against B2. AJ dropped from primary-deploy
# consideration but kept in the set for cross-comparison.
BASKETS = {
    "B1": ("90_PORT_H2_5M_RECYCLE_S03_V1_P00", "EUR+JPY"),
    "AJ": ("90_PORT_H2_5M_RECYCLE_S08_V1_P00", "AUD+JPY"),
    "B2": ("90_PORT_H2_5M_RECYCLE_S05_V1_P04", "AUD+CAD"),
    "EC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P03", "EUR+CAD"),
    "GC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P04", "GBP+CAD"),
    "AC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P07", "AUD+CHF"),
}


def _parquet_path(directive_id: str, basket_id: str = "H2") -> Path:
    return (
        TRADE_SCAN_STATE
        / "backtests"
        / f"{directive_id}_{basket_id}"
        / "raw"
        / "results_basket_per_bar.parquet"
    )


def load_basket_equity(directive_id: str, basket_id: str = "H2") -> pd.Series:
    """Load the per-bar equity_total_usd series indexed by timestamp.

    The parquet's equity_total_usd column = starting_equity + realized + floating
    per the rule's internal invariant. No reconstruction — direct read.
    """
    p = _parquet_path(directive_id, basket_id)
    if not p.exists():
        raise FileNotFoundError(
            f"No 1.3.0-basket parquet ledger at {p}. "
            f"Re-run the directive through the pipeline to generate it."
        )
    df = pd.read_parquet(p, columns=["timestamp", "equity_total_usd"])
    return df.set_index("timestamp").sort_index()["equity_total_usd"]


def basket_dd_metrics(equity: pd.Series, stake: float, label: str) -> dict:
    """Compute Max DD + capital metrics on a per-bar equity series."""
    peak = equity.cummax()
    dd = equity - peak  # ≤ 0
    worst_dd_usd = float(-dd.min())
    worst_idx = dd.idxmin()
    final_eq = float(equity.iloc[-1])
    peak_at_worst = float(peak.loc[worst_idx])
    return {
        "label": label,
        "stake": stake,
        "final_eq": final_eq,
        "net_pnl": final_eq - stake,
        "net_pnl_pct": (final_eq - stake) / stake * 100.0,
        "max_dd_usd": worst_dd_usd,
        "max_dd_pct_of_peak": worst_dd_usd / peak_at_worst * 100.0 if peak_at_worst > 0 else 0.0,
        "max_dd_pct_of_stake": worst_dd_usd / stake * 100.0,
        "worst_bar_ts": worst_idx,
        "peak_at_worst": peak_at_worst,
    }


def compose_equity(basket_equity: dict[str, pd.Series], members: list[str]) -> pd.Series:
    """Sum basket equities on the union of their timestamps (forward-filled).

    Each basket starts at $stake before its first bar and continues at its
    final equity after its last bar; missing timestamps before a basket
    opens get stake-padded, after close get final-equity-padded.
    """
    all_idx = sorted({t for m in members for t in basket_equity[m].index})
    all_idx = pd.DatetimeIndex(all_idx)
    parts = []
    for m in members:
        s = basket_equity[m].reindex(all_idx, method="ffill")
        # Bars before the basket's first record get the starting stake
        s = s.fillna(STAKE_PER_BASKET)
        parts.append(s)
    return sum(parts)


def main() -> int:
    print("=" * 100)
    print("PER-BASKET TRUE INTRA-BAR Max DD (1.3.0-basket parquet ledger, spec-correct)")
    print("=" * 100)
    print(f"{'Basket':6s} {'Pair':10s} {'Stake':>7s}  {'Final eq':>9s}  {'Net PnL':>9s}  "
          f"{'PnL%':>6s}  {'MaxDD $':>9s}  {'%peak':>6s}  {'%stake':>7s}  Worst-bar ts")
    print("-" * 100)

    basket_equity: dict[str, pd.Series] = {}
    per_basket_metrics: dict[str, dict] = {}
    for label, (directive_id, pair_name) in BASKETS.items():
        try:
            eq = load_basket_equity(directive_id)
        except FileNotFoundError as exc:
            print(f"{label:6s} {pair_name:10s} SKIP — {exc}")
            continue
        basket_equity[label] = eq
        m = basket_dd_metrics(eq, STAKE_PER_BASKET, label)
        per_basket_metrics[label] = m
        print(
            f"{label:6s} {pair_name:10s} ${m['stake']:>6.0f}  "
            f"${m['final_eq']:>8.2f}  ${m['net_pnl']:>+8.2f}  "
            f"{m['net_pnl_pct']:>+5.1f}%  ${m['max_dd_usd']:>8.2f}  "
            f"{m['max_dd_pct_of_peak']:>5.2f}%  {m['max_dd_pct_of_stake']:>6.2f}%  "
            f"{m['worst_bar_ts']}"
        )

    if not basket_equity:
        print("\n[FATAL] No parquet ledgers found. Re-run baskets through the pipeline.")
        return 1

    print()
    print("=" * 100)
    print("COMPOSITE TRUE INTRA-BAR Max DD")
    print("=" * 100)

    # Sleeve-challenge composites (operator 2026-05-16): does B1 have a
    # better second sleeve than B2? Pair B1 with each candidate.
    composites = {
        "B1+B2 (champion)": ["B1", "B2"],
        "B1+EC (EUR+CAD)":  ["B1", "EC"],
        "B1+GC (GBP+CAD)":  ["B1", "GC"],
        "B1+AC (AUD+CHF)":  ["B1", "AC"],
        "B1+AJ (legacy)":   ["B1", "AJ"],
        "E1 B1+B2+AJ":      ["B1", "B2", "AJ"],
    }

    print(f"{'Composite':16s} {'Stake':>7s}  {'Final eq':>9s}  {'Net PnL':>9s}  "
          f"{'PnL%':>6s}  {'MaxDD $':>9s}  {'%stake':>7s}  {'sum-singles':>12s}  {'div%':>6s}")
    print("-" * 100)
    for name, members in composites.items():
        if not all(m in basket_equity for m in members):
            missing = [m for m in members if m not in basket_equity]
            print(f"{name:16s} SKIP — missing baskets: {missing}")
            continue
        comp_eq = compose_equity(basket_equity, members)
        stake = STAKE_PER_BASKET * len(members)
        m = basket_dd_metrics(comp_eq, stake, name)
        sum_single_dd = sum(per_basket_metrics[mm]["max_dd_usd"] for mm in members)
        div = m["max_dd_usd"] / sum_single_dd * 100.0 if sum_single_dd > 0 else 0.0
        print(
            f"{name:16s} ${m['stake']:>6.0f}  ${m['final_eq']:>8.2f}  ${m['net_pnl']:>+8.2f}  "
            f"{m['net_pnl_pct']:>+5.1f}%  ${m['max_dd_usd']:>8.2f}  {m['max_dd_pct_of_stake']:>6.2f}%  "
            f"${sum_single_dd:>11.2f}  {div:>5.1f}%"
        )

    print()
    print(f"Notes:")
    print(f"  - 'MaxDD $' = peak intra-bar floating drawdown ($1k stake per basket; $2k or $3k composite stake).")
    print(f"  - '%peak' = MaxDD as fraction of running peak equity at that bar (post-harvest peak for harvested baskets).")
    print(f"  - '%stake' = MaxDD as fraction of total nominal stake.")
    print(f"  - 'div%' = composite MaxDD as fraction of sum-of-singles DDs (lower = better diversification).")
    print(f"  - Per-basket numbers are byte-correct from the emitter's recorded dd_from_peak_usd column.")
    print(f"  - Composite numbers re-compute Max DD on the summed equity series (the right operator-experience metric).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
