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
# LIQUIDATE_TRAIL_STOP added 2026-05-18 (P04 variant): peak-relative trailing
# stop. Activates when running cycle-peak floating >= trail_arm_floating_usd
# AND current floating retraces by trail_retrace_pct%.
# LIQUIDATE_HARVEST_COMPLETE + HARVEST_SCALE_OUT added 2026-05-19 with
# H3_spread@2 (bounded-exposure + harvest scale-out). The @2 rule emits
# HARVEST_SCALE_OUT on each Phase-2 scale-out bar (non-terminal partial
# realization, cycle remains open) and LIQUIDATE_HARVEST_COMPLETE when
# the scale-out chain reduces the residual to zero (terminal exit; the
# leg strategy resumes for the next cross signal).
# HOLD_AT_CAP added 2026-05-19 with the harvest_delay_levels extension:
# threshold crossings at the exposure cap that neither add nor scale-out,
# consumed during the delay window before HARVEST begins.
# SCALE_OUT_TO_CORE + CORE_HOLD added 2026-05-19 with the
# harvest_keeps_core extension: the LAST scale-out lands at initial_lot
# (rather than zero) and emits SCALE_OUT_TO_CORE; subsequent threshold
# crossings emit CORE_HOLD (silent threshold consumption, lot persists
# at the floor until reverse-cross / adverse / time fires).
_H3_SPREAD_TAGS = {"PYRAMID", "AWAITING_ENTRY", "HOLDING",
                   "HARVEST_SCALE_OUT", "HOLD_AT_CAP",
                   "SCALE_OUT_TO_CORE", "CORE_HOLD",
                   "LIQUIDATE_TIME_STOP", "LIQUIDATE_ADVERSE_STOP",
                   "LIQUIDATE_REVERSE_CROSS", "LIQUIDATE_TRAIL_STOP",
                   "LIQUIDATE_HARVEST_COMPLETE"}
# pine_ratio_zrev_v1 (V3, always-in-market reversal): no harvest cycle (the
# harvest threshold is never hit); a "cycle" is one held reversal SEGMENT,
# closed when the z_r flip liquidates+reverses, tagged LIQUIDATE_REVERSAL.
# pine_ratio_zrev_v1_zcross (2026-05-31): zero-crossing exit variant. Same
# cycle shape — one held SEGMENT per propose+approve+open+exit lifecycle —
# but exits tag LIQUIDATE_EQUILIBRIUM (sign-flip) instead of REVERSAL
# (opposite-extreme cross). Both tags share the family for metric purposes.
_PINE_REVERSAL_TAGS = {"LIQUIDATE_REVERSAL", "LIQUIDATE_EQUILIBRIUM"}


def detect_rule_family(df: pd.DataFrame) -> str:
    """Auto-detect rule family from per-bar skip_reason values.

    Returns one of: "h3_spread", "v5_pyramid", "v4_bump_liquidate",
    "pine_reversal", "v1_recycle". Used to drive cycle-level metric reconstruction in
    `canonical_metrics`. Pass `rule_family` explicitly if auto-detect
    would be ambiguous (e.g. zero-event runs).
    """
    if "skip_reason" not in df.columns:
        return "v1_recycle"
    reasons = set(df["skip_reason"].dropna().unique())
    # Check LIQUIDATE_REVERSAL FIRST: it is unique to pine_ratio_zrev_v1, but
    # that rule also emits HOLDING/AWAITING_ENTRY which overlap _H3_SPREAD_TAGS,
    # so the h3 check would otherwise mis-claim it (and then find none of its
    # liquidation tags -> zero cycles -> the all-zero win_rate bug).
    if reasons & _PINE_REVERSAL_TAGS:
        return "pine_reversal"
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


# A completed cycle == one full-basket LIQUIDATION. Every rule family already
# names these events with the shared "LIQUIDATE" convention — LIQUIDATE_RESET
# (v4), TREND_LIQUIDATE_* (v5), LIQUIDATE_TIME_STOP / ..._HARVEST_COMPLETE (h3),
# LIQUIDATE_REVERSAL / ..._EQUILIBRIUM / ..._OPP_REVERT (pine reversal / zcross /
# zopp). Matching the CONVENTION (a substring) rather than a hardcoded per-family
# tag list means a new exit variant is counted the moment it follows the
# convention — closing the class of bug that silently zeroed GP_ZOPP's
# LIQUIDATE_OPP_REVERT. Partial scale-outs (HARVEST_SCALE_OUT / SCALE_OUT_TO_CORE)
# are not liquidations (no "LIQUIDATE" in the tag), so a harvested basket still
# counts as one cycle.
#
# Why a tag CONVENTION and not a pure position signal: a same-direction
# liquidate-and-reopen (a real cycle, e.g. pine zcross) and a v4 bump-add
# (mid-cycle, NOT a cycle) are indistinguishable from the position series alone —
# both realize PnL while staying 2-leg, same-direction. The skip_reason is the
# only thing that separates them, so the robust fix generalizes the tag match
# rather than abandoning it. (Validated: identical counts to the legacy per-family
# path on every existing family; GP_ZOPP now counts.)
_LIQUIDATION_TAG = "LIQUIDATE"


def _cycle_pnl_robust(df: pd.DataFrame) -> list[dict]:
    """Variant-agnostic per-cycle PnL: one cycle per full-basket LIQUIDATION bar
    (`skip_reason` containing the shared "LIQUIDATE" convention); `cycle_pnl_usd`
    is the realized_total_usd delta between consecutive liquidations. A strict
    generalization of the legacy per-family `_cycle_pnl_from_parquet` (identical
    counts on every existing family) that additionally catches exit variants whose
    exact tag was never wired into the per-family list. Same dict shape.
    """
    if df.empty or "skip_reason" not in df.columns or "realized_total_usd" not in df.columns:
        return []
    mask = df["skip_reason"].astype(str).str.contains(
        _LIQUIDATION_TAG, case=True, na=False, regex=False)
    exit_bars = df[mask]
    if exit_bars.empty:
        return []
    has_ts = "timestamp" in df.columns
    cycles: list[dict] = []
    prev_realized = 0.0
    for idx in exit_bars.index:
        row = df.loc[idx]
        post_realized = float(row["realized_total_usd"])
        cycles.append({
            "bar_index": int(idx),
            "ts": row["timestamp"] if has_ts else None,
            "exit_tag": row["skip_reason"],
            "cycle_pnl_usd": post_realized - prev_realized,
            "prev_realized": prev_realized,
            "post_realized": post_realized,
        })
        prev_realized = post_realized
    return cycles


class CycleConventionError(ValueError):
    """A basket run fully closed a position without following the cycle-counting
    naming convention (every full-basket close tagged with 'LIQUIDATE'). Raised to
    FAIL the run loudly — the convention is what makes `_cycle_pnl_robust`
    variant-agnostic, so a silent violation would reintroduce the GP_ZOPP class of
    wrong-cycle-metric bug.
    """


# Families whose cycle metrics are computed (and therefore depend on the
# convention). v1_recycle has no cycle taxonomy, so it is exempt.
_CYCLE_MECHANIC_FAMILIES = frozenset({
    "pine_reversal", "v4_bump_liquidate", "v5_pyramid", "h3_spread",
})


def _assert_liquidation_convention(df: pd.DataFrame, rule_family: str) -> None:
    """Enforce the cycle-counting convention at backtest / metrics time: for a
    cycle-mechanic family, any bar that FULLY closes the basket (active_legs -> 0)
    AND realizes PnL MUST carry a 'LIQUIDATE' skip_reason. Such a bar is exactly a
    completed cycle; tagged otherwise, `_cycle_pnl_robust` silently miscounts it
    (the GP_ZOPP defect). Raising here stops the run before wrong cycle metrics
    reach the ledger. Validated zero false positives across the live cointegration
    corpus + the H2 v4/v5 reference runs (2026-06-05).
    """
    if rule_family not in _CYCLE_MECHANIC_FAMILIES:
        return
    if df.empty or not {"active_legs", "skip_reason", "realized_total_usd"} <= set(df.columns):
        return
    al = pd.to_numeric(df["active_legs"], errors="coerce").fillna(0).tolist()
    rz = pd.to_numeric(df["realized_total_usd"], errors="coerce").fillna(0.0).tolist()
    sk = df["skip_reason"].astype(str).tolist()
    for i in range(1, len(df)):
        if (al[i - 1] > 0 and al[i] == 0
                and abs(rz[i] - rz[i - 1]) > 1e-9
                and _LIQUIDATION_TAG not in sk[i]):
            raise CycleConventionError(
                f"cycle-counting convention violated: basket fully closed and "
                f"realized PnL at bar {int(df.index[i])} with skip_reason={sk[i]!r} "
                f"(rule_family={rule_family}) — it does not contain "
                f"'{_LIQUIDATION_TAG}'. Every full-close event MUST be tagged "
                f"LIQUIDATE_* or canonical_metrics._cycle_pnl_robust will silently "
                f"miscount the cycle. Fix the rule's exit skip_reason."
            )


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
    peak_equity = (
        float(df["peak_equity_usd"].max()) if len(df) else float(stake_usd)
    )
    net_pct = (final_eq - stake_usd) / stake_usd * 100 if stake_usd > 0 else 0.0
    # DD% is peak-relative (standard backtest convention). Predecessor divided
    # by stake_usd which produced > 100% for profitable runs when peak >> stake
    # (e.g. H3_spread BEAR 24mo: DD $1379 / stake $1000 = 138% vs DD/peak = 36%).
    # The stake-relative form is still computed for callers that need it.
    max_dd_pct = peak_dd_usd / peak_equity * 100 if peak_equity > 0 else 0.0
    max_dd_pct_vs_stake = peak_dd_usd / stake_usd * 100 if stake_usd > 0 else 0.0
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
        # H2 v4 / v5 tags
        "bumps":            int((skip == "BUMP_INTO_HOLD").sum()),
        "liquidate_reset":  int((skip == "LIQUIDATE_RESET").sum()),
        "pyramids":         int((skip == "PYRAMID_ADDED").sum()),
        "liq_recovery":     int((skip == "TREND_LIQUIDATE_RECOVERY").sum()),
        "liq_floor":        int((skip == "TREND_LIQUIDATE_FLOOR").sum()),
        "liq_correlation":  int((skip == "TREND_LIQUIDATE_CORRELATION").sum()),
        "correlation_gate_blocks": int((skip == "CORRELATION_GATE").sum()),
        "holding_bars":     int(((skip == "HOLD_MODE") | (skip == "HOLDING_PYRAMID")).sum()),
        "waiting_bars":     int((skip == "WAITING_FOR_PYRAMID").sum()),
        # H3_spread tags (2026-05-18)
        "h3_pyramids":      int((skip == "PYRAMID").sum()),
        "h3_holding":       int((skip == "HOLDING").sum()),
        "h3_awaiting":      int((skip == "AWAITING_ENTRY").sum()),
        "h3_liq_time":      int((skip == "LIQUIDATE_TIME_STOP").sum()),
        "h3_liq_adverse":   int((skip == "LIQUIDATE_ADVERSE_STOP").sum()),
        "h3_liq_reverse":   int((skip == "LIQUIDATE_REVERSE_CROSS").sum()),
        "h3_liq_trail":     int((skip == "LIQUIDATE_TRAIL_STOP").sum()),
        # H3_spread@2 events (2026-05-19)
        "h3_harvest_scaleouts": int((skip == "HARVEST_SCALE_OUT").sum()),
        "h3_liq_harvest":   int((skip == "LIQUIDATE_HARVEST_COMPLETE").sum()),
        "h3_hold_at_cap":   int((skip == "HOLD_AT_CAP").sum()),
        "h3_scale_to_core": int((skip == "SCALE_OUT_TO_CORE").sum()),
        "h3_core_hold":     int((skip == "CORE_HOLD").sum()),
    }

    # Cycle-level reconstruction — variant-agnostic. Any full-basket LIQUIDATION
    # bar (skip_reason containing "LIQUIDATE") is a completed cycle, so a new exit
    # variant cannot silently drop to 0 cycles the way GP_ZOPP's
    # LIQUIDATE_OPP_REVERT did under the old hardcoded per-family tag lists.
    # Strict generalization: validated identical to the legacy per-family counts
    # on every existing family (v4=5 / v5=37,104 / GP / GP_ZCRS / h3) 2026-06-05.
    # Guard FIRST: fail loudly if a full-close skips the LIQUIDATE convention the
    # counter relies on, so a non-conforming new rule is caught here, not in a
    # silently-wrong ledger months later.
    _assert_liquidation_convention(df, rf)
    cycle_pnls = _cycle_pnl_robust(df)

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

    # --- Time-in-position telemetry -------------------------------------
    # Fraction of bars with at least one leg in position. Distinguishes
    # signal-triggered strategies (mostly waiting) from continuous-hold
    # baskets (always open).
    total_bars = len(df)
    if total_bars > 0 and "active_legs" in df.columns:
        in_position_bars = int((df["active_legs"] > 0).sum())
        time_in_position_pct = in_position_bars / total_bars * 100.0
    else:
        in_position_bars = 0
        time_in_position_pct = 0.0

    # --- Cycle-duration distribution (bars between consecutive liquidations) -
    cycle_durations_bars: list[int] = []
    if cycle_pnls:
        prev_bar = 0
        for c in cycle_pnls:
            cycle_durations_bars.append(int(c["bar_index"]) - prev_bar)
            prev_bar = int(c["bar_index"])
    cycle_dur_series = pd.Series(cycle_durations_bars, dtype=float) if cycle_durations_bars else pd.Series(dtype=float)

    # --- Capital efficiency: peak notional / peak equity --------------------
    peak_notional = (
        float(df["notional_total_usd"].max()) if "notional_total_usd" in df.columns and total_bars else 0.0
    )
    peak_leverage_ratio = (peak_notional / peak_equity) if peak_equity > 0 else 0.0

    # --- Recovery time from worst DD ----------------------------------------
    # Bars between the worst-DD bar and the next bar that exceeded the prior peak.
    recovery_bars: Optional[int] = None
    if total_bars and "dd_from_peak_usd" in df.columns:
        worst_idx = int(df["dd_from_peak_usd"].idxmin())
        peak_at_worst = float(df.loc[worst_idx, "peak_equity_usd"])
        after = df.iloc[worst_idx + 1:]
        if not after.empty:
            recovered = after[after["equity_total_usd"] > peak_at_worst]
            if not recovered.empty:
                recovery_bars = int(recovered.index[0]) - worst_idx
            # else stays None → never recovered within the window

    # --- Underwater-period analysis -----------------------------------------
    # An "underwater period" is a contiguous run of bars where equity is
    # below the running peak. The longest such period bounds operator
    # patience expectations ("how many months might I sit at a loss?").
    underwater_periods_bars: list[int] = []
    longest_underwater_bars: int = 0
    if total_bars and "dd_from_peak_usd" in df.columns:
        # underwater = dd_from_peak_usd < 0 (strictly below peak)
        uw = (df["dd_from_peak_usd"] < 0).to_numpy()
        # Run-length encode True spans
        in_run = False
        run_len = 0
        for v in uw:
            if v:
                run_len += 1
                in_run = True
            elif in_run:
                underwater_periods_bars.append(run_len)
                run_len = 0
                in_run = False
        if in_run:
            underwater_periods_bars.append(run_len)
        if underwater_periods_bars:
            longest_underwater_bars = max(underwater_periods_bars)
    n_underwater_periods = len(underwater_periods_bars)
    underwater_total_bars = sum(underwater_periods_bars)
    underwater_total_pct = (
        underwater_total_bars / total_bars * 100.0 if total_bars else 0.0
    )

    # --- Monthly equity curve -----------------------------------------------
    # Year-month bucketing: starting equity, ending equity, MTD return %, and
    # cycle count per month. Operators use this to spot regime windows where
    # the strategy worked vs failed.
    monthly_rows: list[dict[str, Any]] = []
    if total_bars and "timestamp" in df.columns:
        ts_series = pd.to_datetime(df["timestamp"])
        df_ts = df.assign(_month=ts_series.dt.to_period("M").astype(str))
        # Map each cycle to its month
        cycle_months: dict[str, int] = {}
        for c in cycle_pnls:
            cts = c.get("ts")
            if cts is None:
                continue
            try:
                ym = pd.Timestamp(cts).to_period("M").strftime("%Y-%m")
                cycle_months[ym] = cycle_months.get(ym, 0) + 1
            except Exception:
                continue
        grouped = df_ts.groupby("_month", sort=True)
        for month, sub in grouped:
            start_eq = float(sub["equity_total_usd"].iloc[0])
            end_eq = float(sub["equity_total_usd"].iloc[-1])
            mtd_pct = ((end_eq - start_eq) / start_eq * 100.0) if start_eq > 0 else 0.0
            monthly_rows.append({
                "month": str(month),
                "starting_equity": start_eq,
                "ending_equity": end_eq,
                "mtd_return_pct": mtd_pct,
                "n_cycles": cycle_months.get(str(month), 0),
            })

    # --- Per-cycle PnL histogram (adaptive bucketing) -----------------------
    # 7 buckets across the observed range. The bucket boundaries are
    # rounded to the nearest sensible currency value (cent / dollar).
    pnl_histogram: list[dict[str, Any]] = []
    if cycle_pnls:
        pnl_values = [c["cycle_pnl_usd"] for c in cycle_pnls]
        s = pd.Series(pnl_values, dtype=float)
        # Use seven quantile-based buckets; falls back to equal-width if
        # quantiles collapse (e.g., all values identical).
        try:
            bins = pd.qcut(s, q=7, duplicates="drop")
        except ValueError:
            bins = pd.cut(s, bins=7, duplicates="drop")
        counts = bins.value_counts().sort_index()
        for interval, n in counts.items():
            pnl_histogram.append({
                "lo": float(interval.left),
                "hi": float(interval.right),
                "count": int(n),
                "share_pct": float(n) / len(s) * 100.0,
            })

    # --- Exit reason breakdown (for cycle-mechanic rules) -------------------
    exit_breakdown: dict[str, int] = {}
    if cycle_pnls:
        from collections import Counter
        c = Counter(cp.get("exit_tag", "?") for cp in cycle_pnls)
        exit_breakdown = dict(c)

    # --- Per-leg cumulative floating contribution at end --------------------
    leg_final_lots: dict[str, float] = {}
    leg_final_floats: dict[str, float] = {}
    if total_bars:
        last_row = df.iloc[-1]
        for lot_col, sym_col in zip(leg_lot_cols, leg_sym_cols):
            sym = df[sym_col].dropna().iloc[0] if not df[sym_col].dropna().empty else None
            if not sym:
                continue
            leg_final_lots[sym] = float(last_row.get(lot_col, 0.0))
            float_col = lot_col.replace("_lot", "_floating_usd")
            if float_col in df.columns:
                leg_final_floats[sym] = float(last_row.get(float_col, 0.0))

    return {
        # Headline
        "final_equity_usd":   final_eq,
        "peak_equity_usd":    peak_equity,
        "net_pct":            net_pct,
        "max_dd_usd":         peak_dd_usd,
        "max_dd_pct":         max_dd_pct,             # peak-relative (standard)
        "max_dd_pct_vs_stake": max_dd_pct_vs_stake,    # stake-relative (legacy / capital sizing)
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
        "exit_breakdown":     exit_breakdown,     # {tag: count} for cycle exits
        "cycle_durations_bars": cycle_durations_bars,  # bars between liquidations

        # Asymmetry diagnostic (per-winner-side)
        "per_winner_side":    per_winner_side,

        # Per-leg peak exposure (for capital sizing)
        "peak_lots":          peak_lots,
        "leg_final_lots":     leg_final_lots,
        "leg_final_floats":   leg_final_floats,

        # Time / capital telemetry
        "time_in_position_pct": time_in_position_pct,
        "in_position_bars":   in_position_bars,
        "total_bars":         total_bars,
        "peak_notional_usd":  peak_notional,
        "peak_leverage_ratio": peak_leverage_ratio,
        "recovery_bars":      recovery_bars,

        # Underwater + monthly + histogram telemetry (2026-05-18)
        "longest_underwater_bars": longest_underwater_bars,
        "underwater_periods_bars": underwater_periods_bars,
        "n_underwater_periods": n_underwater_periods,
        "underwater_total_bars": underwater_total_bars,
        "underwater_total_pct": underwater_total_pct,
        "monthly_curve":      monthly_rows,
        "pnl_histogram":      pnl_histogram,

        # Rule context
        "rule_family":        rf,
    }


__all__ = ["canonical_metrics", "detect_rule_family"]
