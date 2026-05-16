"""h2_deployment_posture.py -- live deployment capital requirements.

[NEW 2026-05-16] Computes operator-facing deployment posture for H2 baskets
from the 1.3.0-basket parquet ledger:

  - required live capital (per FX_BASKET_RECYCLE_RESEARCH.md sec 4.15:
      real_capital_required = max(peak_margin_used, 2 * peak_floating_dd_usd))
  - margin buffer (min margin_level_pct over basket lifetime)
  - DD multiple (peak_floating_dd_usd / stake)
  - return on deployed capital (net_pnl / real_capital_required)

For composites: shows both the "naive sum" (sum of per-basket real-capitals)
and "diversification-aware" (composite_stake + 2 * composite_max_dd) so
operator can see how much diversification reduces the capital ask.

Inputs: parquet ledgers at TradeScan_State/backtests/<id>_H2/raw/.
Outputs: per-basket and per-composite deployment tables.

This is the bottom-line module: every other section feeds into the
deployment decision; this section reports the answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.path_authority import TRADE_SCAN_STATE
from tools.harvest_robustness.modules.h2_intrabar_floating_dd import (
    BASKETS, STAKE_PER_BASKET, basket_dd_metrics, compose_equity, load_basket_equity,
)


def _full_parquet(directive_id: str) -> pd.DataFrame:
    p = (
        TRADE_SCAN_STATE
        / "backtests"
        / f"{directive_id}_H2"
        / "raw"
        / "results_basket_per_bar.parquet"
    )
    return pd.read_parquet(p)


def per_basket_deployment_metrics(label: str, directive_id: str, pair: str) -> dict | None:
    """Load parquet + compute deployment metrics for one basket."""
    try:
        df = _full_parquet(directive_id)
    except FileNotFoundError:
        return None
    df = df.set_index("timestamp").sort_index()
    equity = df["equity_total_usd"]
    final_pnl = float(equity.iloc[-1]) - STAKE_PER_BASKET

    peak_dd_usd = abs(float(df["dd_from_peak_usd"].min()))
    peak_margin_used = float(df["margin_used_usd"].max())
    min_margin_level = float(df.loc[df["margin_used_usd"] > 0, "margin_level_pct"].min())
    peak_lot = float(df["largest_leg_lot"].max())

    real_capital = max(peak_margin_used, 2.0 * peak_dd_usd)
    roc = final_pnl / real_capital * 100.0 if real_capital > 0 else 0.0
    dd_multiple = peak_dd_usd / STAKE_PER_BASKET

    return {
        "label":              label,
        "pair":               pair,
        "stake":              STAKE_PER_BASKET,
        "final_pnl":          final_pnl,
        "final_pnl_pct":      final_pnl / STAKE_PER_BASKET * 100.0,
        "peak_dd_usd":        peak_dd_usd,
        "peak_dd_pct_stake":  peak_dd_usd / STAKE_PER_BASKET * 100.0,
        "peak_margin_used":   peak_margin_used,
        "min_margin_level":   min_margin_level,
        "peak_lot":           peak_lot,
        "real_capital":       real_capital,
        "dd_multiple":        dd_multiple,
        "roc_pct":            roc,
        "equity_series":      equity,
    }


def main() -> int:
    # Per-basket
    per_basket: dict[str, dict] = {}
    for label, (directive_id, pair) in BASKETS.items():
        m = per_basket_deployment_metrics(label, directive_id, pair)
        if m is None:
            continue
        per_basket[label] = m

    if not per_basket:
        print("[FATAL] No parquet ledgers found. Re-run baskets through the pipeline.")
        return 1

    print("=" * 110)
    print("PER-BASKET DEPLOYMENT POSTURE (1.3.0-basket parquet; operator-facing capital truth)")
    print("=" * 110)
    print(f"{'Basket':6s} {'Pair':10s} {'Stake':>7s}  {'Net PnL':>9s}  {'PnL%':>6s}  "
          f"{'Peak DD':>8s}  {'DD%':>6s}  {'PeakMargin':>10s}  {'MinML%':>7s}  "
          f"{'PeakLot':>7s}  {'RealCap':>8s}  {'DDx':>5s}  {'ROC%':>7s}")
    print("-" * 110)
    for m in per_basket.values():
        print(
            f"{m['label']:6s} {m['pair']:10s} ${m['stake']:>6.0f}  "
            f"${m['final_pnl']:>+8.2f}  {m['final_pnl_pct']:>+5.1f}%  "
            f"${m['peak_dd_usd']:>7.2f}  {m['peak_dd_pct_stake']:>5.2f}%  "
            f"${m['peak_margin_used']:>9.2f}  {m['min_margin_level']:>6.0f}%  "
            f"{m['peak_lot']:>6.3f}  ${m['real_capital']:>7.2f}  "
            f"{m['dd_multiple']:>4.2f}x  {m['roc_pct']:>6.1f}%"
        )

    # Composite section
    from itertools import combinations
    print()
    print("=" * 110)
    print("COMPOSITE DEPLOYMENT POSTURE")
    print("=" * 110)
    print(f"{'Composite':14s} {'N':>2s}  {'Stake':>7s}  {'Net PnL':>9s}  {'PnL%':>6s}  "
          f"{'Comp DD':>8s}  {'DD%':>6s}  {'CapSum':>9s}  {'CapDiv':>9s}  {'ROCSum':>7s}  {'ROCDiv':>7s}")
    print("-" * 110)

    available = sorted(per_basket.keys())
    basket_equity = {k: per_basket[k]["equity_series"] for k in available}

    composite_results = []
    for k in (1, 2, 3):
        if len(available) < k:
            continue
        for combo in combinations(available, k):
            if k == 1:
                label = f"{combo[0]} ({per_basket[combo[0]]['pair']})"
                comp_eq = basket_equity[combo[0]]
            else:
                label = "+".join(combo)
                comp_eq = compose_equity(basket_equity, list(combo))
            stake = STAKE_PER_BASKET * len(combo)
            mm = basket_dd_metrics(comp_eq, stake, label)
            comp_dd = mm["max_dd_usd"]
            net_pnl = mm["net_pnl"]
            # Naive sum-of-singles capital
            cap_sum = sum(per_basket[m]["real_capital"] for m in combo)
            # Diversification-aware composite capital
            cap_div = max(
                sum(per_basket[m]["peak_margin_used"] for m in combo),  # margin floor
                2.0 * comp_dd,
            )
            roc_sum = net_pnl / cap_sum * 100.0 if cap_sum > 0 else 0.0
            roc_div = net_pnl / cap_div * 100.0 if cap_div > 0 else 0.0
            composite_results.append({
                "label":    label,
                "n":        len(combo),
                "stake":    stake,
                "net_pnl":  net_pnl,
                "pnl_pct":  net_pnl / stake * 100.0,
                "comp_dd":  comp_dd,
                "dd_pct":   comp_dd / stake * 100.0,
                "cap_sum":  cap_sum,
                "cap_div":  cap_div,
                "roc_sum":  roc_sum,
                "roc_div":  roc_div,
            })

    # Sort by ROC-div descending (operator's headline metric)
    composite_results.sort(key=lambda r: -r["roc_div"])
    for r in composite_results:
        print(
            f"{r['label']:14s} {r['n']:>2d}  ${r['stake']:>6.0f}  "
            f"${r['net_pnl']:>+8.2f}  {r['pnl_pct']:>+5.1f}%  "
            f"${r['comp_dd']:>7.2f}  {r['dd_pct']:>5.2f}%  "
            f"${r['cap_sum']:>8.2f}  ${r['cap_div']:>8.2f}  "
            f"{r['roc_sum']:>6.1f}%  {r['roc_div']:>6.1f}%"
        )

    print()
    print("Column legend:")
    print("  Peak DD       = max floating drawdown across basket lifetime ($)")
    print("  DD%           = peak DD / stake (per basket) or / composite stake")
    print("  PeakMargin    = max margin tied up at any bar ($)")
    print("  MinML%        = closest the basket came to a broker margin call (equity / margin_used * 100)")
    print("  PeakLot       = maximum any single leg's lot grew to over the cycle")
    print("  RealCap       = max(peak_margin, 2 * peak_dd) -- per FX_BASKET_RECYCLE_RESEARCH sec 4.15 rule")
    print("  DDx           = peak_dd / stake (operator-facing DD-multiple)")
    print("  ROC%          = net_pnl / RealCap * 100 (return on deployed capital)")
    print("  CapSum        = sum of per-basket RealCap (naive sizing without diversification credit)")
    print("  CapDiv        = max(sum-of-peak-margins, 2 * composite Max DD) (diversification-aware)")
    print("  ROCSum/ROCDiv = net_pnl / CapSum or CapDiv (lower CapDiv = higher ROCDiv = composite leverage benefit)")
    print()
    print("Notes:")
    print("  - All numbers derived from the spec-correct 1.3.0-basket parquet ledger; no reload+replay.")
    print("  - Diversification credit appears as the gap between CapSum and CapDiv (the lower, the better).")
    print("  - For deployment sizing, use CapDiv as the floor and CapSum as the conservative ceiling.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
