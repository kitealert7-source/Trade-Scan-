"""h2_intrabar_floating_dd.py -- LEGACY intra-bar floating Max DD reconstruction.

[DEPRECATED 2026-05-16] This module is DEPRECATED. Two state-model bugs
overstate Max DD on every H2 basket where legs grew above the initial 0.01
lot (which is essentially all of them under H2 mechanics):

  Bug 1 (line ~87): `state[winner] = {"lot": 0.01, ...}` resets the winner's
    lot to the hardcoded initial 0.01 on every realize event. The
    research-validated rule mechanic in `tools/research/basket_sim.py:362,388`
    is explicit: "Close winner: realize full floating, reset avg to current
    price (lot unchanged)". Effect: when a leg that previously grew (as a
    loser) later wins, the timeline incorrectly shrinks its lot, distorting
    all subsequent per-bar floating PnL.

  Bug 2 (line ~150): uses `data[leg]["open"].iloc[0]` (bar 0's open) as the
    initial avg_entry. The engine actually fills at bar 1's open per the
    next_bar_open execution timing. Causes a small (~$0.30 for B1)
    persistent offset in the pre-first-event window.

  Empirical impact (B1 forensic, outputs/H2_TELEMETRY_PARITY_FORENSIC.md):
    this module reported Max DD = $494.71. The spec-correct emitter and the
    on-disk recycle_events.jsonl independently confirm Max DD = $325.11.
    ~52% overstatement. Other H2 baskets show 5-35% overstatement depending
    on how much their legs grew.

Authoritative replacement: read `results_basket_per_bar.parquet` directly.
  - Path: TradeScan_State/backtests/<directive_id>_<basket_id>/raw/
  - Schema: 1.3.0-basket (35 fixed + 8*N leg columns; see
    tools/basket_report.py `_FIXED_LEDGER_COLUMNS` / `_PER_LEG_SUFFIXES`).
  - Read example:
      df = pd.read_parquet(parquet_path)
      max_dd_usd = abs(df["dd_from_peak_usd"].min())   # spec-correct DD
      worst_dd_bar = df.loc[df["dd_from_peak_usd"].idxmin()]
  - For composite baskets: union timestamps across per-basket parquets,
    forward-fill per-basket equity, sum, recompute Max DD on the composite
    series. Per-basket parquets are independently correct.

This module is retained ONLY for replay of legacy basket runs that pre-date
the 1.3.0-basket schema (schema_version "1.2.0-basket" in run_metadata.json,
no parquet on disk). For any basket with a per-bar parquet, prefer the
parquet read. A Phase 7 refactor (plan §9) will rewrite this module to
default to parquet-read with the reload+replay path kept as a fallback for
schema_version < 1.3.0; bugs 1 and 2 will be fixed at that point.

---

ORIGINAL DESIGN INTENT (preserved for historical context):

The realized DDs from results_tradelevel.csv and the at-event floating snapshots
from recycle_events.jsonl both miss the worst-case INTRA-BAR floating PnL between
recycle events. This script reconstructs the per-5m-bar floating PnL by:

  1. Parsing recycle_events.jsonl to build a leg-state timeline
     (lot, avg_entry per symbol over time).
  2. Loading 5m OHLC data for each leg via basket_data_loader.
  3. For each 5m bar, computing floating PnL per leg using BOTH bar close
     (mid-resolution estimate) AND bar low (worst-case for long positions).
  4. Tracking realized cumulative + floating per bar -> equity curve.
  5. Computing Max DD at the per-bar resolution (both close-based and
     low-based).

Then rolls up per-basket curves into composite equity curves and reports
the TRUE intra-bar Max DD per composite -- the answer to "what's the worst
my account balance would look like at any 5m bar during the run."

Caveat: the low-based estimate assumes all legs hit their bar-low simultaneously,
which is a worst-case correlation assumption. The close-based estimate is more
realistic mid-bar. True operator experience is between the two.
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # modules/ -> harvest_robustness/ -> tools/ -> repo
sys.path.insert(0, str(PROJECT_ROOT))

from tools.basket_data_loader import load_basket_leg_data

from config.path_authority import DRY_RUN_VAULT
VAULT = DRY_RUN_VAULT / "baskets"
STAKE_PER_BASKET = 1000.0
CONTRACT_SIZE = 100_000  # OctaFx FX: 1 lot = 100,000 base ccy units

# (label, directive_id, leg1, leg2, start_date)
BASKETS = {
    "B1": ("90_PORT_H2_5M_RECYCLE_S03_V1_P00", "EURUSD", "USDJPY", "2024-09-02"),
    "AJ": ("90_PORT_H2_5M_RECYCLE_S08_V1_P00", "AUDUSD", "USDJPY", "2024-09-02"),
    "GJ": ("90_PORT_H2_5M_RECYCLE_S08_V1_P01", "GBPUSD", "USDJPY", "2024-09-02"),
    "B2": ("90_PORT_H2_5M_RECYCLE_S05_V1_P04", "AUDUSD", "USDCAD", "2024-09-02"),
    "GC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P04", "GBPUSD", "USDCAD", "2024-09-02"),
    "EC": ("90_PORT_H2_5M_RECYCLE_S08_V1_P03", "EURUSD", "USDCAD", "2024-09-02"),
}

# USD-quote pairs: long = bet on quote ccy weakening vs USD; PnL = (close - entry) * lot * 100k (in USD directly)
# USD-base pairs (long = long USD): PnL = (close - entry) * lot * 100k / close (in USD via dividing by quote rate)
USD_QUOTE = {"EURUSD", "AUDUSD", "GBPUSD", "NZDUSD"}
USD_BASE = {"USDJPY", "USDCHF", "USDCAD"}


def pnl_usd(symbol: str, current_price: float, avg_entry: float, lot: float, direction: int = 1) -> float:
    """Compute floating PnL in USD for a USD-anchored leg."""
    raw = (current_price - avg_entry) * direction * lot * CONTRACT_SIZE
    if symbol in USD_QUOTE:
        return raw
    elif symbol in USD_BASE:
        # PnL is in quote currency; convert to USD by dividing by current quote rate
        return raw / current_price if current_price > 0 else 0.0
    else:
        raise ValueError(f"symbol {symbol} not USD-anchored")


def reconstruct_leg_state_timeline(events: list[dict], legs: list[str], start_bar_ts: pd.Timestamp,
                                     start_prices: dict[str, float]) -> dict[str, pd.DataFrame]:
    """Build per-leg state timeline: at each event timestamp, what's the (lot, avg_entry)?
    Initial state at start_bar_ts: lot=0.01, avg_entry=start_prices[leg].
    """
    state = {leg: {"lot": 0.01, "avg_entry": start_prices[leg]} for leg in legs}
    timelines = {leg: [] for leg in legs}
    # Record initial state
    for leg in legs:
        timelines[leg].append({"ts": start_bar_ts, **state[leg]})

    for event in events:
        ts = pd.Timestamp(event["bar_ts"])
        winner = event["winner_symbol"]
        loser = event["loser_symbol"]
        # Winner: realized fully, resets to 0.01 lot at winner_new_entry (current price)
        state[winner] = {"lot": 0.01, "avg_entry": event["winner_new_entry"]}
        # Loser: lot grows, avg_entry updates
        state[loser] = {"lot": event["loser_new_lot"], "avg_entry": event["loser_new_avg"]}
        timelines[winner].append({"ts": ts, **state[winner]})
        timelines[loser].append({"ts": ts, **state[loser]})

    return {leg: pd.DataFrame(timelines[leg]).set_index("ts").sort_index() for leg in legs}


def per_bar_floating_pnl(leg_data: pd.DataFrame, state_timeline: pd.DataFrame, symbol: str,
                          price_col: str = "close") -> pd.Series:
    """For each bar in leg_data, compute floating PnL using the leg's state at that bar.

    State timeline is forward-filled onto the bar index (state holds between events).
    """
    # Reindex state to bar timestamps, forward-fill
    bar_state = state_timeline.reindex(leg_data.index, method="ffill")
    # Fill any leading NaNs (bars before first event) with the initial state (first row of timeline)
    bar_state = bar_state.fillna(method="bfill")
    # Compute floating PnL per bar
    prices = leg_data[price_col]
    floating = (prices - bar_state["avg_entry"]) * bar_state["lot"] * CONTRACT_SIZE
    if symbol in USD_BASE:
        floating = floating / prices.replace(0, np.nan)
    return floating.fillna(0)


def per_bar_realized_cumulative(events: list[dict], bar_index: pd.DatetimeIndex) -> pd.Series:
    """Cumulative realized PnL at each bar (sums all events up to and including that bar)."""
    if not events:
        return pd.Series(0.0, index=bar_index)
    ev_df = pd.DataFrame([{"ts": pd.Timestamp(e["bar_ts"]), "realized": e["winner_realized"]} for e in events])
    ev_df = ev_df.set_index("ts").sort_index()
    cum = ev_df["realized"].cumsum()
    return cum.reindex(bar_index, method="ffill").fillna(0)


def per_bar_basket_equity(label: str, directive_id: str, leg1: str, leg2: str,
                           start_date: str, end_date: str = "2026-05-15") -> pd.DataFrame:
    """Reconstruct basket equity curve at 5m resolution.

    Returns DataFrame with columns: eq_close, eq_low (worst-case intra-bar).
    """
    # Load events
    events_path = VAULT / directive_id / "H2" / "recycle_events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    # Identify last event time + buffer for end_date
    if events:
        last_event_ts = pd.Timestamp(events[-1]["bar_ts"])
        # Use realized exit timestamp from tradelevel CSV for end_date
        from config.path_authority import TRADE_SCAN_STATE as _TSS
        tlp = _TSS / "backtests" / f"{directive_id}_H2" / "raw" / "results_tradelevel.csv"
        tldf = pd.read_csv(tlp)
        tldf["exit_timestamp"] = pd.to_datetime(tldf["exit_timestamp"])
        basket_end = tldf["exit_timestamp"].max()
        end_date = basket_end.strftime("%Y-%m-%d")
    # Load 5m data
    data = load_basket_leg_data([leg1, leg2], start_date, end_date)
    # Common bar index = intersection
    bar_idx = data[leg1].index.intersection(data[leg2].index)
    data[leg1] = data[leg1].loc[bar_idx]
    data[leg2] = data[leg2].loc[bar_idx]
    # Start bar = first bar
    start_bar_ts = bar_idx[0]
    start_prices = {leg1: float(data[leg1]["open"].iloc[0]),
                    leg2: float(data[leg2]["open"].iloc[0])}
    # Reconstruct state timeline
    state_timelines = reconstruct_leg_state_timeline(events, [leg1, leg2], start_bar_ts, start_prices)
    # Per-bar floating PnL per leg, using BOTH close and low (worst-case intra-bar for longs)
    floating_close = {
        leg: per_bar_floating_pnl(data[leg], state_timelines[leg], leg, "close")
        for leg in [leg1, leg2]
    }
    floating_low = {
        leg: per_bar_floating_pnl(data[leg], state_timelines[leg], leg, "low")
        for leg in [leg1, leg2]
    }
    # Per-bar realized cumulative
    realized = per_bar_realized_cumulative(events, bar_idx)
    # Equity curves
    floating_close_total = pd.DataFrame(floating_close).sum(axis=1)
    floating_low_total = pd.DataFrame(floating_low).sum(axis=1)
    eq_close = STAKE_PER_BASKET + realized + floating_close_total
    eq_low = STAKE_PER_BASKET + realized + floating_low_total
    return pd.DataFrame({
        "eq_close": eq_close,
        "eq_low": eq_low,
        "realized_cum": realized,
        "floating_close": floating_close_total,
        "floating_low": floating_low_total,
    }, index=bar_idx)


def basket_dd_metrics(eq_series: pd.Series, stake: float, label: str) -> dict:
    """Compute Max DD on a per-bar equity curve."""
    peak = eq_series.cummax()
    dd = eq_series - peak
    worst_dd_usd = float(-dd.min())
    worst_idx = dd.idxmin()
    worst_eq = float(eq_series.loc[worst_idx])
    peak_at_worst = float(peak.loc[worst_idx])
    final_eq = float(eq_series.iloc[-1])
    return {
        "label": label,
        "stake": stake,
        "final_eq": final_eq,
        "net_pnl": final_eq - stake,
        "net_pnl_pct": (final_eq - stake) / stake * 100,
        "max_dd_usd": worst_dd_usd,
        "max_dd_pct_of_peak": worst_dd_usd / peak_at_worst * 100 if peak_at_worst > 0 else 0,
        "max_dd_pct_of_stake": worst_dd_usd / stake * 100,
        "worst_bar_ts": worst_idx,
        "equity_at_worst": worst_eq,
        "peak_at_worst": peak_at_worst,
    }


def main() -> int:
    print("Reconstructing per-bar floating PnL for each basket...")
    basket_eqs = {}
    for label, (did, leg1, leg2, sd) in BASKETS.items():
        try:
            df = per_bar_basket_equity(label, did, leg1, leg2, sd)
            basket_eqs[label] = df
            n = len(df)
            print(f"  {label:5s} ({leg1}+{leg2}): {n} bars, last bar {df.index[-1]}")
        except Exception as exc:
            print(f"  {label:5s} ERROR: {exc}")
            import traceback; traceback.print_exc()

    print()
    print("=" * 130)
    print("PER-BASKET TRUE INTRA-BAR Max DD")
    print("=" * 130)
    print(f"{'Basket':6s} {'Stake':>6s}  {'Final eq':>9s}  {'Net PnL':>9s}  "
          f"{'MaxDD ($) close':>16s}  {'%peak':>6s}  {'%stake':>7s}  "
          f"{'MaxDD ($) LOW':>14s}  {'%peak':>6s}  {'%stake':>7s}  Worst ts")
    print("-" * 130)
    per_basket_close_metrics = {}
    per_basket_low_metrics = {}
    for label, df in basket_eqs.items():
        mc = basket_dd_metrics(df["eq_close"], STAKE_PER_BASKET, label)
        ml = basket_dd_metrics(df["eq_low"], STAKE_PER_BASKET, label)
        per_basket_close_metrics[label] = mc
        per_basket_low_metrics[label] = ml
        print(
            f"{label:6s} ${mc['stake']:>5.0f}  ${mc['final_eq']:>8.2f}  ${mc['net_pnl']:>+8.2f}  "
            f"{mc['max_dd_usd']:>16.2f}  {mc['max_dd_pct_of_peak']:>5.2f}%  {mc['max_dd_pct_of_stake']:>6.2f}%  "
            f"{ml['max_dd_usd']:>14.2f}  {ml['max_dd_pct_of_peak']:>5.2f}%  {ml['max_dd_pct_of_stake']:>6.2f}%  "
            f"{mc['worst_bar_ts']}"
        )

    print()
    print("=" * 130)
    print("COMPOSITE TRUE INTRA-BAR Max DD (per-bar union, forward-filled per-basket equity, summed)")
    print("=" * 130)

    composites = {
        "SINGLE B1": ["B1"],
        "SINGLE AJ": ["AJ"],
        "SINGLE GJ": ["GJ"],
        "PAIR B1+AJ": ["B1", "AJ"],
        "PAIR B1+GJ": ["B1", "GJ"],
        "PAIR AJ+GJ": ["AJ", "GJ"],
        "TRIPLE B1+AJ+GJ": ["B1", "AJ", "GJ"],
        "REF B1+B2": ["B1", "B2"],
        "E1 B1+AJ+B2": ["B1", "AJ", "B2"],
        "E2 B1+AJ+B2+GC": ["B1", "AJ", "B2", "GC"],
        "BONUS B1+B2+GC": ["B1", "B2", "GC"],
        "BONUS B2+GC+EC": ["B2", "GC", "EC"],
    }

    print(f"{'Composite':22s} {'Stake':>6s}  {'Final eq':>9s}  {'Net PnL':>9s}  {'PnL%':>6s}  "
          f"{'MaxDD ($) close':>16s}  {'%peak':>6s}  {'%stake':>7s}  "
          f"{'MaxDD ($) LOW':>14s}  {'%peak':>6s}  {'%stake':>7s}")
    print("-" * 130)
    composite_results = []
    for name, members in composites.items():
        if not all(m in basket_eqs for m in members):
            print(f"{name:22s} SKIP (missing baskets)")
            continue
        # Union bar index
        all_idx = sorted({t for m in members for t in basket_eqs[m].index})
        all_idx = pd.DatetimeIndex(all_idx)
        # Sum forward-filled per-basket equity
        comp_close = sum(basket_eqs[m]["eq_close"].reindex(all_idx, method="ffill").fillna(STAKE_PER_BASKET) for m in members)
        comp_low = sum(basket_eqs[m]["eq_low"].reindex(all_idx, method="ffill").fillna(STAKE_PER_BASKET) for m in members)
        stake = STAKE_PER_BASKET * len(members)
        mc = basket_dd_metrics(comp_close, stake, name)
        ml = basket_dd_metrics(comp_low, stake, name)
        composite_results.append((name, mc, ml))
        print(
            f"{name:22s} ${mc['stake']:>5.0f}  ${mc['final_eq']:>8.2f}  ${mc['net_pnl']:>+8.2f}  "
            f"{mc['net_pnl_pct']:>+5.1f}%  "
            f"{mc['max_dd_usd']:>16.2f}  {mc['max_dd_pct_of_peak']:>5.2f}%  {mc['max_dd_pct_of_stake']:>6.2f}%  "
            f"{ml['max_dd_usd']:>14.2f}  {ml['max_dd_pct_of_peak']:>5.2f}%  {ml['max_dd_pct_of_stake']:>6.2f}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
