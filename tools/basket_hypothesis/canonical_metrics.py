"""canonical_metrics.py — single-source-of-truth metrics for basket runs.

The basket per-bar parquet (`results_basket_per_bar.parquet`) is the
authoritative ledger for any basket-strategy run. This module computes
ONE consistent set of metrics from that parquet, replacing the divergent
trade-level computations in the legacy `tools/basket_report.py`,
`tools/portfolio/basket_ledger_writer.py`, and any ad-hoc analysis
scripts.

Why this exists
---------------
The legacy reporting was designed for classic entry-exit strategies
where the `results_tradelevel.csv` records every economically-meaningful
event. Cycle-mechanic rules (H2_recycle@4 bump-and-liquidate, @5
pyramid-and-liquidate, future variants) generate `recycle_events`
that are NOT in the trade-level table. The result:

  Legacy REPORT.md fields    Truth (from parquet)         Bug class
  ---------------------------------------------------------------------
  Trades = 2                 145 pyramids + 104 liq        counts DATA_END only
  Win Rate = 100%            ~59% cycle-level              over force-close only
  Max DD = $0 / 0%           $195.91 / 19.59%              DD over 2 trades
  Profit Factor = inf        finite                        gross loss = 0

This module reads the parquet, auto-detects rule version from the
event taxonomy in the `skip_reason` column, and returns canonical
metrics that downstream surfaces (BASKET_REPORT.md, MPS Baskets row,
at-a-glance) all use.

Per-cycle metrics for cycle-mechanic rules are reconstructed from
`realized_total_usd` deltas at liquidation bars — see §"Cycle PnL
reconstruction" below.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd


# Skip-reason tags by rule family (used for auto-detection)
_V5_TAGS = {"PYRAMID_ADDED", "TREND_LIQUIDATE_RECOVERY",
            "TREND_LIQUIDATE_FLOOR", "TREND_LIQUIDATE_CORRELATION",
            "HOLDING_PYRAMID", "WAITING_FOR_PYRAMID", "CORRELATION_GATE"}
_V4_TAGS = {"BUMP_INTO_HOLD", "LIQUIDATE_RESET", "HOLD_MODE",
            "BUMP_REJECTED_MARGIN", "HOLD_NO_TREND_WINNER"}
# H3_spread@1 (2026-05-18): LONG-SHORT pair-spread basket rule.
# Distinct event vocabulary; HOLDING/PYRAMID/LIQUIDATE_<reason> forms.
_H3_SPREAD_TAGS = {"PYRAMID", "AWAITING_ENTRY", "HOLDING",
                   "LIQUIDATE_TIME_STOP", "LIQUIDATE_ADVERSE_STOP",
                   "LIQUIDATE_REVERSE_CROSS"}


def detect_rule_family(df: pd.DataFrame) -> str:
    """Auto-detect rule family from per-bar skip_reason values.

    Returns one of: "h3_spread", "v5_pyramid", "v4_bump_liquidate",
    "v1_recycle". Used to drive cycle-level metric reconstruction in
    `canonical_metrics`. Pass `rule_family` explicitly if auto-detect
    would be ambiguous (e.g. zero-event runs).
    """
    if "skip_reason" not in df.columns:
        return "v1_recycle"
    reasons = set(df["skip_reason"].dropna().unique())
    if reasons & _H3_SPREAD_TAGS:
        return "h3_spread"
    if reasons & _V5_TAGS:
        return "v5_pyramid"
    if reasons & _V4_TAGS:
        return "v4_bump_liquidate"
    return "v1_recycle"


def _cycle_pnl_from_parquet(
    df: pd.DataFrame, exit_tags: list[str],
) -> list[dict]:
    """Reconstruct per-cycle PnL by tracking realized_total deltas at
    liquidation bars.

    The rule's `realized_total_usd` accumulates monotonically through
    liquidation events (each liquidation: realized += floating_total).
    A cycle's realized PnL is the delta between two consecutive
    liquidation bars (or between cycle-start and first liquidation).

    Returns list of {bar_index, ts, exit_tag, cycle_pnl_usd,
                     prev_realized, post_realized}.
    """
    exit_bars = df[df["skip_reason"].isin(exit_tags)].copy()
    if exit_bars.empty:
        return []
    cycles = []
    prev_realized = 0.0
    for idx in exit_bars.index:
        row = df.loc[idx]
        post_realized = float(row["realized_total_usd"])
        cycle_pnl = post_realized - prev_realized
        cycles.append({
            "bar_index": int(idx),
            "ts": row["timestamp"] if "timestamp" in row else None,
            "exit_tag": row["skip_reason"],
            "cycle_pnl_usd": cycle_pnl,
            "prev_realized": prev_realized,
            "post_realized": post_realized,
        })
        prev_realized = post_realized
    return cycles


def _per_winner_side_breakdown(
    df: pd.DataFrame, exit_tags: list[str],
) -> dict[str, dict[str, Any]]:
    """For 2-leg baskets, break down liquidations by which leg was the
    winner at the moment of exit.

    Reads leg_0_floating_usd vs leg_1_floating_usd on the PREVIOUS bar
    (current bar shows post-soft-reset state with floats ~= 0). Returns
    a per-symbol dict of {total, hard_floor, recovery}.

    Asymmetry diagnostic: large differences in hard_floor rate between
    legs flag pip-value-asymmetric architectures (e.g. EURUSD+USDJPY at
    1:1 ratio).
    """
    # Identify leg symbols from columns
    leg_sym_cols = [c for c in df.columns if c.startswith("leg_") and c.endswith("_symbol")]
    if len(leg_sym_cols) != 2:
        return {}   # only meaningful for 2-leg baskets
    leg_syms = []
    for col in sorted(leg_sym_cols):
        sym = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
        if sym:
            leg_syms.append(sym)
    if len(leg_syms) != 2:
        return {}

    exit_bars = df[df["skip_reason"].isin(exit_tags)].copy()
    if exit_bars.empty:
        return {sym: {"total": 0, "hard_floor": 0, "recovery": 0,
                      "loss_rate_pct": 0.0} for sym in leg_syms}

    per_sym = {sym: {"total": 0, "hard_floor": 0, "recovery": 0,
                    "loss_rate_pct": 0.0} for sym in leg_syms}

    # Determine which tag is "hard floor" vs "recovery" by inspection
    hard_floor_tags = {"TREND_LIQUIDATE_FLOOR"}
    recovery_tags   = {"TREND_LIQUIDATE_RECOVERY", "LIQUIDATE_RESET"}

    for liq_idx in exit_bars.index:
        if liq_idx == 0:
            continue
        prev = df.loc[liq_idx - 1]
        leg_0_float = prev.get("leg_0_floating_usd", 0.0)
        leg_1_float = prev.get("leg_1_floating_usd", 0.0)
        # Winner = leg with higher floating PnL at moment of exit
        winner_sym = leg_syms[0] if leg_0_float > leg_1_float else leg_syms[1]
        per_sym[winner_sym]["total"] += 1
        tag = exit_bars.loc[liq_idx, "skip_reason"]
        if tag in hard_floor_tags:
            per_sym[winner_sym]["hard_floor"] += 1
        elif tag in recovery_tags:
            per_sym[winner_sym]["recovery"] += 1

    # Compute loss_rate per side
    for sym, d in per_sym.items():
        if d["total"] > 0:
            d["loss_rate_pct"] = d["hard_floor"] / d["total"] * 100
    return per_sym


def canonical_metrics(
    parquet_path: str | Path,
    stake_usd: float,
    *,
    basket_csv_path: str | Path | None = None,
    rule_family: str | None = None,
) -> dict[str, Any]:
    """Single canonical metrics extractor for any basket run.

    Args:
        parquet_path: path to `results_basket_per_bar.parquet`.
        stake_usd: the directive's `basket.initial_stake_usd` value.
            Used as denominator for net_pct and max_dd_pct.
        basket_csv_path: optional path to `results_basket.csv` for
            exit_reason / days_to_exit. If omitted, inferred from
            parquet_path's parent.
        rule_family: optional override for auto-detection
            ("v1_recycle" | "v4_bump_liquidate" | "v5_pyramid").

    Returns a dict with:
      - Headline: final_equity_usd, net_pct, max_dd_usd, max_dd_pct,
                  ret_dd, exit_reason, days_to_exit, stake_usd
      - Events:   recycle_executed, bumps, liquidate_reset, pyramids,
                  liq_recovery, liq_floor, holding_bars, waiting_bars
      - Cycle:    cycle_win_rate_pct, cycles_completed, cycles_won,
                  cycles_lost, median_cycle_pnl, mean_cycle_pnl
      - Asymmetry: per_winner_side {sym -> {total, hard_floor, recovery,
                                              loss_rate_pct}}
      - Per-leg:  peak_lots {sym -> peak_lot_during_run}
      - Rule:     rule_family ("v1_recycle" | "v4_bump_liquidate" |
                                "v5_pyramid")
    """
    parquet_path = Path(parquet_path)
    df = pd.read_parquet(parquet_path)

    # Auto-detect rule family
    rf = rule_family or detect_rule_family(df)

    # Headline
    final_eq = float(df["equity_total_usd"].iloc[-1]) if len(df) else float(stake_usd)
    peak_dd_usd = (
        float((df["peak_equity_usd"] - df["equity_total_usd"]).max())
        if len(df) else 0.0
    )
    net_pct = (final_eq - stake_usd) / stake_usd * 100 if stake_usd > 0 else 0.0
    max_dd_pct = peak_dd_usd / stake_usd * 100 if stake_usd > 0 else 0.0
    ret_dd = (net_pct / max_dd_pct) if max_dd_pct > 0 else 0.0

    # Exit reason + days (from basket csv, if available)
    exit_reason: Optional[str] = None
    days_to_exit: Optional[int] = None
    csv_path = (
        Path(basket_csv_path) if basket_csv_path
        else parquet_path.parent / "results_basket.csv"
    )
    if csv_path.is_file():
        try:
            bdf = pd.read_csv(csv_path)
            if "exit_reason" in bdf.columns and len(bdf):
                exit_reason = str(bdf["exit_reason"].iloc[0])
            if "days_to_exit" in bdf.columns and len(bdf):
                days_to_exit = int(bdf["days_to_exit"].iloc[0])
        except (OSError, ValueError, KeyError):
            pass

    # Event counts (taxonomy by rule family)
    skip = df["skip_reason"] if "skip_reason" in df.columns else pd.Series(dtype=str)
    events = {
        "recycle_executed": int(df["recycle_executed"].sum())
                            if "recycle_executed" in df.columns else 0,
        "bumps":            int((skip == "BUMP_INTO_HOLD").sum()),
        "liquidate_reset":  int((skip == "LIQUIDATE_RESET").sum()),
        "pyramids":         int((skip == "PYRAMID_ADDED").sum()),
        "liq_recovery":     int((skip == "TREND_LIQUIDATE_RECOVERY").sum()),
        "liq_floor":        int((skip == "TREND_LIQUIDATE_FLOOR").sum()),
        "liq_correlation":  int((skip == "TREND_LIQUIDATE_CORRELATION").sum()),
        "correlation_gate_blocks": int((skip == "CORRELATION_GATE").sum()),
        "holding_bars":     int(((skip == "HOLD_MODE") | (skip == "HOLDING_PYRAMID")).sum()),
        "waiting_bars":     int((skip == "WAITING_FOR_PYRAMID").sum()),
    }

    # Cycle-level reconstruction (only meaningful for cycle-mechanic rules)
    cycle_pnls: list[dict] = []
    if rf == "v5_pyramid":
        cycle_pnls = _cycle_pnl_from_parquet(
            df, ["TREND_LIQUIDATE_RECOVERY", "TREND_LIQUIDATE_FLOOR", "TREND_LIQUIDATE_CORRELATION"]
        )
    elif rf == "v4_bump_liquidate":
        cycle_pnls = _cycle_pnl_from_parquet(df, ["LIQUIDATE_RESET"])

    cycles_completed = len(cycle_pnls)
    cycles_won = sum(1 for c in cycle_pnls if c["cycle_pnl_usd"] > 0)
    cycles_lost = sum(1 for c in cycle_pnls if c["cycle_pnl_usd"] < 0)
    cycle_win_rate_pct = (
        cycles_won / cycles_completed * 100 if cycles_completed > 0 else 0.0
    )
    cycle_pnl_values = [c["cycle_pnl_usd"] for c in cycle_pnls]
    median_cycle_pnl = (
        float(pd.Series(cycle_pnl_values).median()) if cycle_pnl_values else 0.0
    )
    mean_cycle_pnl = (
        float(sum(cycle_pnl_values) / len(cycle_pnl_values))
        if cycle_pnl_values else 0.0
    )

    # Per-winner-side asymmetry (only meaningful for 2-leg cycle-mechanic runs)
    per_winner_side: dict[str, dict[str, Any]] = {}
    if rf == "v5_pyramid":
        per_winner_side = _per_winner_side_breakdown(
            df, ["TREND_LIQUIDATE_RECOVERY", "TREND_LIQUIDATE_FLOOR", "TREND_LIQUIDATE_CORRELATION"]
        )
    elif rf == "v4_bump_liquidate":
        per_winner_side = _per_winner_side_breakdown(df, ["LIQUIDATE_RESET"])

    # Per-leg peak lots (for capital sizing / Martingale-tail diagnostic)
    leg_lot_cols = [c for c in df.columns if c.startswith("leg_") and c.endswith("_lot")]
    peak_lots: dict[str, float] = {}
    leg_sym_cols = [c.replace("_lot", "_symbol") for c in leg_lot_cols]
    for lot_col, sym_col in zip(leg_lot_cols, leg_sym_cols):
        if sym_col not in df.columns:
            continue
        sym = df[sym_col].dropna().iloc[0] if not df[sym_col].dropna().empty else None
        if sym:
            peak_lots[sym] = float(df[lot_col].max())

    return {
        # Headline
        "final_equity_usd":   final_eq,
        "net_pct":            net_pct,
        "max_dd_usd":         peak_dd_usd,
        "max_dd_pct":         max_dd_pct,
        "ret_dd":             ret_dd,
        "exit_reason":        exit_reason,
        "days_to_exit":       days_to_exit,
        "stake_usd":          stake_usd,

        # Events (taxonomy)
        "events":             events,

        # Cycle-level
        "cycle_win_rate_pct": cycle_win_rate_pct,
        "cycles_completed":   cycles_completed,
        "cycles_won":         cycles_won,
        "cycles_lost":        cycles_lost,
        "median_cycle_pnl":   median_cycle_pnl,
        "mean_cycle_pnl":     mean_cycle_pnl,
        "cycle_pnls":         cycle_pnls,         # full list for distribution analysis

        # Asymmetry diagnostic (per-winner-side)
        "per_winner_side":    per_winner_side,

        # Per-leg peak exposure (for capital sizing)
        "peak_lots":          peak_lots,

        # Rule context
        "rule_family":        rf,
    }


__all__ = ["canonical_metrics", "detect_rule_family"]
