"""basket_report.py — cycle-aware BASKET_REPORT.md generator.

Writes `BASKET_REPORT_<directive_id>.md` alongside the legacy
`REPORT_<directive_id>.md` (which counts only trade-level events and
mis-reports for cycle-mechanic rules). The new report sources every
number from `canonical_metrics()` so REPORT, MPS Baskets row, and the
basket-hypothesis-testing orchestrator's at-a-glance all agree.

The legacy REPORT.md stays for backward compatibility — anything that
parses it (e.g. cross-strategy aggregators) continues to work. The new
BASKET_REPORT.md is authoritative for cycle-mechanic baskets and is
the file the operator should read for deployment decisions.

Naming follows the convention of the legacy generator
(tools/basket_report.py:794) but with a `BASKET_` prefix so the two
coexist in the same directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from tools.basket_hypothesis.canonical_metrics import canonical_metrics
from tools.basket_hypothesis.mfe_giveback import compute_mfe_giveback


def _fmt_money(x: float) -> str:
    return f"${x:>+,.2f}" if x >= 0 else f"-${abs(x):>,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x:>+.2f}%"


def _fmt_int(x: int | None) -> str:
    return f"{x:>,}" if x is not None else "—"


def _rule_family_label(rf: str) -> str:
    return {
        "v1_recycle":         "H2_recycle@1/@2/@3 (Variant G)",
        "v4_bump_liquidate":  "H2_recycle@4 (bump-and-liquidate)",
        "v5_pyramid":         "H2_recycle@5 (trend-follow pyramid)",
        "h3_spread":          "H3_spread@1 (pair-spread pyramid + adverse / reverse-cross / time exits)",
    }.get(rf, rf)


def _fmt_bars(n: int | None, bar_seconds: int = 300) -> str:
    """Convert bar count to human-readable duration (5m default)."""
    if n is None:
        return "—"
    secs = n * bar_seconds
    days = secs // 86400
    hours = (secs % 86400) // 3600
    if days >= 1:
        return f"{n:,} bars ({days}d {hours}h)"
    minutes = (secs % 3600) // 60
    return f"{n:,} bars ({hours}h {minutes}m)"


def _build_top_line_table(m: dict[str, Any]) -> str:
    """Top-line metrics: net%, DD% (peak-relative), ret/DD, equity, exit."""
    final_eq = m["final_equity_usd"]
    peak_eq = m.get("peak_equity_usd", final_eq)
    stake = m["stake_usd"]
    lines = [
        "## Top-Line Metrics (canonical — parquet-derived)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stake (initial) | {_fmt_money(stake)} |",
        f"| Peak equity | {_fmt_money(peak_eq)} |",
        f"| Final equity | {_fmt_money(final_eq)} |",
        f"| Net PnL | {_fmt_money(final_eq - stake)} |",
        f"| **Net %** | **{_fmt_pct(m['net_pct'])}** |",
        f"| Max DD (USD) | {_fmt_money(-m['max_dd_usd'])} |",
        f"| **Max DD % (peak-relative)** | **{_fmt_pct(-m['max_dd_pct'])}** |",
        f"| Max DD % (vs. stake) | {_fmt_pct(-m.get('max_dd_pct_vs_stake', 0.0))} |",
        f"| **Return / DD** | **{m['ret_dd']:.2f}** |",
        f"| Exit reason | {m['exit_reason'] or '—'} |",
        f"| Days to exit | {_fmt_int(m['days_to_exit'])} |",
    ]
    return "\n".join(lines)


def _build_event_taxonomy_table(m: dict[str, Any]) -> str:
    """Event counts by rule family — only show rows relevant to the
    detected rule family to keep the table tight.

    Pass-2 fix #10: when the rule family is unrecognized (or `events`
    dict is empty), fall back to a placeholder body instead of rendering
    a bare section header with no rows underneath (looks like a render
    bug to the reader).
    """
    ev = m["events"]
    rf = m["rule_family"]
    lines = ["## Event Taxonomy", ""]
    if rf == "v1_recycle":
        lines.extend([
            "| Event | Count |",
            "|---|---|",
            f"| Recycle events executed | {_fmt_int(ev['recycle_executed'])} |",
        ])
    elif rf == "v4_bump_liquidate":
        lines.extend([
            "| Event | Count |",
            "|---|---|",
            f"| Recycle events (Mode 1) | {_fmt_int(ev['recycle_executed'])} |",
            f"| Bumps (Mode 1 → 2 trigger) | {_fmt_int(ev['bumps'])} |",
            f"| Liquidations (soft-reset) | {_fmt_int(ev['liquidate_reset'])} |",
            f"| Holding bars (Mode 2) | {_fmt_int(ev['holding_bars'])} |",
        ])
    elif rf == "v5_pyramid":
        lines.extend([
            "| Event | Count |",
            "|---|---|",
            f"| Pyramids (add to winner) | {_fmt_int(ev['pyramids'])} |",
            f"| Liquidations: recovery exit | {_fmt_int(ev['liq_recovery'])} |",
            f"| Liquidations: hard floor | {_fmt_int(ev['liq_floor'])} |",
            f"| Holding bars (in pyramid cycle) | {_fmt_int(ev['holding_bars'])} |",
            f"| Waiting bars (pre-first-pyramid) | {_fmt_int(ev['waiting_bars'])} |",
        ])
    elif rf == "h3_spread":
        n_trail = ev.get("h3_liq_trail", 0)
        n_scaleouts = ev.get("h3_harvest_scaleouts", 0)
        n_harvest = ev.get("h3_liq_harvest", 0)
        n_hold = ev.get("h3_hold_at_cap", 0)
        n_to_core = ev.get("h3_scale_to_core", 0)
        n_core_hold = ev.get("h3_core_hold", 0)
        total_liq = (
            ev["h3_liq_time"] + ev["h3_liq_adverse"] + ev["h3_liq_reverse"]
            + n_trail + n_harvest
        )
        lines.extend([
            "| Event | Count | Notes |",
            "|---|---|---|",
            f"| Pyramids (Phase-1 add to both legs) | {_fmt_int(ev['h3_pyramids'])} | anti-Martingale add when basket P&L crosses threshold below cap |",
            f"| Hold-at-cap (delayed-harvest window) | {_fmt_int(n_hold)} | threshold crossings consumed at cap before harvest begins (@2 w/ harvest_start_after_extra_pyramids > 0) |",
            f"| Harvest scale-outs (Phase-2) | {_fmt_int(n_scaleouts)} | symmetric partial realization above the cap (@2 only) |",
            f"| Scale-out-to-core (final, keeps_core=True) | {_fmt_int(n_to_core)} | last scale-out landing at initial_lot (residual rides on) |",
            f"| Core-hold bars (persistent trend) | {_fmt_int(n_core_hold)} | threshold crossings post-harvest at the floor (@2 w/ harvest_keeps_core=True) |",
            f"| Liquidations — TIME stop | {_fmt_int(ev['h3_liq_time'])} | basket aged out of position window |",
            f"| Liquidations — ADVERSE stop | {_fmt_int(ev['h3_liq_adverse'])} | basket P&L below adverse threshold |",
            f"| Liquidations — TRAIL stop | {_fmt_int(n_trail)} | peak-relative retracement after running peak armed |",
            f"| Liquidations — REVERSE cross | {_fmt_int(ev['h3_liq_reverse'])} | regime-flip detected via cross_side inversion |",
            f"| Liquidations — HARVEST complete | {_fmt_int(n_harvest)} | Phase-2 scale-outs reduced residual to zero (@2 only) |",
            f"| Liquidations (total) | {_fmt_int(total_liq)} | sum of above five |",
            f"| Holding bars (in position) | {_fmt_int(ev['h3_holding'])} | basket open + waiting for trigger |",
            f"| Awaiting-entry bars | {_fmt_int(ev['h3_awaiting'])} | flat, waiting for next cross signal |",
        ])
    # Pass-2 fix #10: empty-body guard. If the rule family wasn't matched
    # above (unknown / unrecognized) OR the events dict was empty, we'd
    # leave a bare header — reads as a render bug. Suppress the section
    # entirely in that case rather than emitting a header with no rows.
    if len(lines) <= 2:
        if not ev:
            return ""  # nothing to show — suppress header (pass-2 fix #10)
        # Rule family unrecognized but events dict has content: render a
        # minimal placeholder so the data is at least visible.
        lines.extend([
            f"_(no taxonomy template for rule_family=`{rf}`; showing raw counts)_",
            "",
            "| Event key | Count |",
            "|---|---|",
        ])
        for k in sorted(ev.keys()):
            lines.append(f"| `{k}` | {_fmt_int(ev[k])} |")
    return "\n".join(lines)


def _build_cycle_breakdown_table(m: dict[str, Any]) -> str:
    """Per-cycle PnL distribution + win rate. Only meaningful for cycle
    mechanics. For H3_spread / v4 / v5: reconstructed from realized_total
    deltas at liquidation bars in the per-bar parquet."""
    if m["rule_family"] == "v1_recycle":
        return ""  # not applicable
    rec = m["cycles_completed"]
    if rec == 0:
        return "## Cycle Breakdown\n\n(no liquidation events — basket ran continuously)\n"
    pnls = [c["cycle_pnl_usd"] for c in m["cycle_pnls"]]
    pnl_s = pd.Series(pnls) if pnls else pd.Series(dtype=float)
    pos_pnls = pnl_s[pnl_s > 0]
    neg_pnls = pnl_s[pnl_s < 0]
    pf = (pos_pnls.sum() / -neg_pnls.sum()) if len(neg_pnls) and neg_pnls.sum() < 0 else float("inf")
    pct_lines = []
    if len(pnl_s) >= 10:
        for q, label in [(0.05, "p05"), (0.25, "p25"), (0.50, "p50"), (0.75, "p75"), (0.95, "p95")]:
            pct_lines.append(f"| {label} cycle PnL | {_fmt_money(float(pnl_s.quantile(q)))} |")
    lines = [
        "## Cycle Breakdown (reconstructed from per-bar realized_total deltas)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cycles completed | {rec} |",
        f"| Cycles won (PnL > 0) | {m['cycles_won']} |",
        f"| Cycles lost (PnL < 0) | {m['cycles_lost']} |",
        f"| **Cycle win rate** | **{m['cycle_win_rate_pct']:.1f}%** |",
        (f"| Cycle profit factor (gross_win / gross_loss) | {pf:.2f} |"
         if pf != float("inf")
         else "| Cycle profit factor | inf (no losing cycles) |"),
        f"| Mean cycle PnL | {_fmt_money(m['mean_cycle_pnl'])} |",
        f"| Median cycle PnL | {_fmt_money(m['median_cycle_pnl'])} |",
        f"| StdDev cycle PnL | {_fmt_money(float(pnl_s.std()) if len(pnl_s) > 1 else 0.0)} |",
        f"| Best cycle | {_fmt_money(pnl_s.max() if len(pnl_s) else 0)} |",
        f"| Worst cycle | {_fmt_money(pnl_s.min() if len(pnl_s) else 0)} |",
        *pct_lines,
    ]
    # Append exit-reason breakdown if cycles tracked it
    eb = m.get("exit_breakdown") or {}
    if eb:
        lines.extend([
            "",
            "### Exit-reason mix",
            "",
            "| Exit reason | Count | Share |",
            "|---|---|---|",
        ])
        for tag, n in sorted(eb.items(), key=lambda kv: -kv[1]):
            share = n / rec * 100 if rec else 0.0
            lines.append(f"| `{tag}` | {n} | {share:.1f}% |")
    # Append cycle-duration distribution
    durs = m.get("cycle_durations_bars") or []
    if durs:
        dur_s = pd.Series(durs)
        # Median bar-seconds detection: peek at parquet timeframe if available;
        # downstream report-rendering only cares about ranges; default 5m.
        lines.extend([
            "",
            "### Cycle duration distribution (bars between consecutive liquidations)",
            "",
            "| Stat | Value |",
            "|---|---|",
            f"| Min | {int(dur_s.min())} bars |",
            f"| p25 | {int(dur_s.quantile(0.25))} bars |",
            f"| Median | {int(dur_s.median())} bars |",
            f"| p75 | {int(dur_s.quantile(0.75))} bars |",
            f"| Max | {int(dur_s.max())} bars |",
            f"| Mean | {dur_s.mean():.0f} bars |",
        ])
    return "\n".join(lines)


def _build_asymmetry_table(m: dict[str, Any]) -> str:
    """Per-winner-side asymmetry diagnostic for 2-leg cycle-mechanic
    baskets. Surfaces the pip-value-asymmetry pattern we diagnosed in
    H3 V1 (EUR-winner cycles dying at hard floor disproportionately)."""
    per = m["per_winner_side"]
    if not per:
        return ""
    lines = [
        "## Per-Winner-Side Asymmetry (diagnostic)",
        "",
        "Distribution of liquidation outcomes by which leg was the",
        "winner at the moment of exit. Large rate gaps signal pip-value",
        "or position-sizing asymmetry between legs (e.g. EURUSD+USDJPY",
        "at 1:1 ratio has $0.10/pip vs $0.067/pip imbalance).",
        "",
        "| Winner symbol | Total cycles | Recovery exits | Hard-floor exits | Floor rate |",
        "|---|---|---|---|---|",
    ]
    for sym, d in per.items():
        lines.append(
            f"| {sym} | {d['total']} | {d['recovery']} | {d['hard_floor']} | "
            f"**{d['loss_rate_pct']:.1f}%** |"
        )
    # Asymmetry ratio
    if len(per) == 2:
        rates = [d["loss_rate_pct"] for d in per.values()]
        if min(rates) > 0:
            ratio = max(rates) / min(rates)
            lines.extend([
                "",
                f"**Asymmetry ratio** (max/min floor rate): **{ratio:.2f}×**  "
                f"_(1.0× = perfectly symmetric; >1.5× suggests pip-value or "
                f"sizing imbalance)_",
            ])
    return "\n".join(lines)


def _build_peak_lots_table(m: dict[str, Any]) -> str:
    """Per-leg peak lot exposure — for capital sizing (Martingale-tail
    diagnostic)."""
    pl = m["peak_lots"]
    if not pl:
        return ""
    final_lots = m.get("leg_final_lots") or {}
    lines = [
        "## Per-Leg Exposure",
        "",
        "Peak = largest lot during the run (pyramid-stack max).",
        "Final = lot at end of window (in-position) or 0.0 (flat).",
        "",
        "| Symbol | Peak lot | Final lot |",
        "|---|---|---|",
    ]
    for sym, lot in pl.items():
        fin = final_lots.get(sym, 0.0)
        lines.append(f"| {sym} | {lot:.3f} | {fin:.3f} |")
    return "\n".join(lines)


def _build_underwater_section(m: dict[str, Any]) -> str:
    """Drawdown-duration analytics: longest contiguous underwater period
    + total % of time spent below the running peak. Operators read this
    to size their patience expectations ("can I tolerate N months at a
    loss?")."""
    n_periods = m.get("n_underwater_periods", 0)
    if not n_periods:
        return ""
    longest = m.get("longest_underwater_bars", 0)
    total_uw = m.get("underwater_total_bars", 0)
    total_pct = m.get("underwater_total_pct", 0.0)
    recovery = m.get("recovery_bars")
    lines = [
        "## Underwater Curve",
        "",
        "An underwater bar is one where equity sits below the running peak.",
        "Long underwater periods test operator patience; the worst-DD",
        "depth is already in the Top-Line table — this is about *time*.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Distinct underwater periods | {n_periods:,} |",
        f"| **Longest underwater period** | **{_fmt_bars(longest)}** |",
        f"| Total bars underwater | {total_uw:,} |",
        f"| **Share of run underwater** | **{total_pct:.1f}%** |",
        f"| Recovery time from worst DD | {_fmt_bars(recovery)} |",
    ]
    return "\n".join(lines)


def _build_monthly_curve_table(m: dict[str, Any]) -> str:
    """Month-by-month equity progression — exposes regime windows where
    the strategy worked vs failed. Annual aggregates hide bull-run-only
    edges; monthly aggregates surface them."""
    rows = m.get("monthly_curve") or []
    if not rows:
        return ""
    lines = [
        "## Monthly Equity Curve",
        "",
        "Per-calendar-month: equity start/end, MTD return %, and number",
        "of cycles that liquidated in the month.",
        "",
        "| Month | Start equity | End equity | MTD return | Cycles |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['month']} | {_fmt_money(r['starting_equity'])} | "
            f"{_fmt_money(r['ending_equity'])} | "
            f"{_fmt_pct(r['mtd_return_pct'])} | {r['n_cycles']} |"
        )
    return "\n".join(lines)


def _build_pnl_histogram_table(m: dict[str, Any]) -> str:
    """Per-cycle PnL distribution histogram — visualizes the bimodal
    'many small losers + few huge winners' shape that percentiles only
    hint at.

    Pass-2 fix #2: rebuild from `cycle_pnls` using evenly-spaced edges
    (linspace from min to max in 7 buckets) instead of relying on the
    quantile-equalized `pnl_histogram` that canonical_metrics still
    pre-computes. Quantile equalization produced ~equal counts per bucket
    by construction, hiding the actual distribution shape. Evenly-spaced
    edges show variable bar widths reflecting real distribution mass.
    """
    cycle_pnls_meta = m.get("cycle_pnls") or []
    if not cycle_pnls_meta:
        return ""
    vals = [c.get("cycle_pnl_usd", 0.0) for c in cycle_pnls_meta if c]
    if not vals:
        return ""
    import numpy as _np
    arr = _np.asarray([float(v) for v in vals], dtype=float)
    n_total = int(arr.size)
    if n_total == 0:
        return ""

    N_BUCKETS = 7
    BAR_WIDTH = 30
    lo, hi = float(arr.min()), float(arr.max())
    if lo == hi:
        # Degenerate: all values identical. Single-bucket display.
        buckets = [{
            "lo": lo, "hi": hi, "count": n_total,
            "share_pct": 100.0,
        }]
    else:
        # Evenly-spaced edges from min to max. Right-open intervals except
        # the last, so max is always captured.
        edges = _np.linspace(lo, hi, N_BUCKETS + 1).tolist()
        buckets = []
        for i in range(N_BUCKETS):
            e_lo = edges[i]
            e_hi = edges[i + 1]
            if i == N_BUCKETS - 1:
                mask = (arr >= e_lo) & (arr <= e_hi)
            else:
                mask = (arr >= e_lo) & (arr < e_hi)
            cnt = int(mask.sum())
            buckets.append({
                "lo": e_lo,
                "hi": e_hi,
                "count": cnt,
                "share_pct": (cnt / n_total * 100.0) if n_total else 0.0,
            })

    max_count = max((b["count"] for b in buckets), default=0)
    lines = [
        "## Cycle-PnL Distribution",
        "",
        "Seven evenly-spaced buckets across `[min_cycle_pnl, max_cycle_pnl]`",
        "(fixed-width, not quantile-equalized). Variable bar lengths show",
        "the true distribution shape — bimodal 'many small losers + few",
        "huge winners' patterns are visible at a glance.",
        "",
        "| PnL range (USD) | Count | Share | Distribution |",
        "|---|---|---|---|",
    ]
    for b in buckets:
        if max_count and b["count"] > 0:
            bar_len = int(round(b["count"] / max_count * BAR_WIDTH))
            bar = "█" * max(bar_len, 1)
        else:
            bar = "."
        lines.append(
            f"| {_fmt_money(b['lo'])} → {_fmt_money(b['hi'])} | "
            f"{b['count']} | {b['share_pct']:.1f}% | `{bar}` |"
        )
    return "\n".join(lines)


_SMALL_N_THRESHOLD = 10  # below this, the new tradelevel-derived sections suppress


def _small_n_notice(section_title: str, n: int) -> str:
    """Render a one-line suppression notice for tradelevel-derived sections
    when the leg-trade sample is too small to support a histogram or table."""
    return (
        f"## {section_title}\n"
        "\n"
        f"_(suppressed: N={n} leg-trades; below small-sample threshold)_"
    )


def _population_line(n: int) -> str:
    """Population banner displayed at the top of each tradelevel-derived
    section. Says explicitly that one cycle in a 2-leg basket records two
    leg-trade rows, so the reader can map N back to cycles."""
    # 2-leg basket convention; the //2 is the most common case. We say
    # "= N/2 cycles x 2 legs" so a reader doing the arithmetic gets it
    # right without us having to introspect leg_count here.
    return f"_Population: {n} leg-trades (= {n // 2} cycles x 2 legs)_"


# Fixed R-bucket edges (Pass-2 fix #1). Replaces quantile-equalized buckets
# which collapsed to a single bar when all R-values were negative.
_FIXED_R_EDGES = (float("-inf"), -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, float("inf"))
_FIXED_R_LABELS = (
    "<-2R",
    "[-2,-1)R",
    "[-1,0)R",
    "[0,+1)R",
    "[+1,+2)R",
    "[+2,+3)R",
    ">=+3R",
)


def _build_r_multiple_histogram(tl_df: pd.DataFrame) -> str:
    """Per-leg-trade R-multiple distribution histogram.

    Uses FIXED bucket edges [-inf, -2, -1, 0, +1, +2, +3, +inf] so the
    histogram shape is invariant across runs and an all-losing leg-trade
    population shows up as concentrated mass in the negative buckets rather
    than collapsing to a single quantile-equalized bucket (Pass-2 fix #1).

    Each row is one leg-trade (2 rows per cycle for 2-leg baskets).
    R-multiple = realized PnL / risk_distance at entry.

    Returns empty string if tl_df is empty or r_multiple all-NaN.
    Returns a small-N notice if N < _SMALL_N_THRESHOLD.
    """
    if tl_df.empty or "r_multiple" not in tl_df.columns:
        return ""
    r = tl_df["r_multiple"].dropna()
    if r.empty:
        return ""

    n_total = len(r)
    if n_total < _SMALL_N_THRESHOLD:
        return _small_n_notice("R-Multiple Distribution (per leg-trade)", n_total)

    BAR_WIDTH = 30
    edges = list(_FIXED_R_EDGES)
    labels = list(_FIXED_R_LABELS)

    # Bucketize with right-open edges except the last (closed).
    buckets = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        if i == len(edges) - 2:
            mask = (r >= lo) & (r <= hi)
        else:
            mask = (r >= lo) & (r < hi)
        cnt = int(mask.sum())
        buckets.append({
            "label": labels[i],
            "lo": lo,
            "hi": hi,
            "count": cnt,
            "share_pct": (cnt / n_total * 100.0) if n_total else 0.0,
        })

    max_count = max((b["count"] for b in buckets), default=0)
    lines = [
        "## R-Multiple Distribution (per leg-trade)",
        "",
        _population_line(n_total),
        "",
        "Fixed bucket edges `[-inf, -2, -1, 0, +1, +2, +3, +inf]` so the",
        "distribution shape is invariant across runs. Each row is one",
        "leg-trade (2 rows per cycle for 2-leg baskets). R-multiple =",
        "realized PnL / risk_distance at entry. Empty buckets render with",
        "count 0 and a single-dot bar so the full shape is always visible.",
        "",
        "| R-multiple range | Count | Share | Distribution |",
        "|---|---|---|---|",
    ]
    for b in buckets:
        if max_count and b["count"] > 0:
            bar_len = int(round(b["count"] / max_count * BAR_WIDTH))
            bar = "█" * max(bar_len, 1)
        else:
            # Empty bucket: single-dot placeholder so the row is visually
            # distinct from a populated bucket but the shape is still
            # auditable (the bug Reviewer 5 spotted).
            bar = "."
        lines.append(
            f"| {b['label']} | {b['count']} | {b['share_pct']:.1f}% | `{bar}` |"
        )
    lines.extend([
        "",
        f"**Median R-multiple:** {float(r.median()):+.3f}R",
        f"**Mean R-multiple:** {float(r.mean()):+.3f}R",
    ])
    return "\n".join(lines)


def _build_vol_regime_breakdown(tl_df: pd.DataFrame) -> str:
    """Per-leg-trade breakdown by volatility regime.

    Groups leg-trades by `volatility_regime` (int -1/0/+1 expected;
    strings handled defensively). Each row is one leg-trade — see caption.

    Pass-2 fix #5: adds "Share of leg-trades %" column so per-regime
    exposure weight is visible alongside per-regime quality.
    Pass-2 fix #6: prepends population line.
    Pass-2 fix #7: small-N guard suppresses when total leg-trades < threshold.

    Returns empty string if volatility_regime missing or all-NaN.
    """
    if tl_df.empty or "volatility_regime" not in tl_df.columns:
        return ""
    vr = tl_df["volatility_regime"].dropna()
    if vr.empty:
        return ""

    n_total = len(tl_df)
    if n_total < _SMALL_N_THRESHOLD:
        return _small_n_notice("Volatility Regime Breakdown (per leg-trade)", n_total)

    df = tl_df.dropna(subset=["volatility_regime"]).copy()
    n_classified = len(df)

    # Sort key: numeric -1/0/+1 ordering when possible; otherwise lexical.
    def _sort_key(v):
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (1, str(v))

    regimes = sorted(df["volatility_regime"].unique().tolist(), key=_sort_key)

    def _regime_label(v):
        # Friendly labels for the canonical -1/0/+1 ints.
        try:
            iv = int(v)
            return {-1: "-1 (low vol)", 0: "0 (mid vol)", 1: "+1 (high vol)"}.get(iv, str(iv))
        except (TypeError, ValueError):
            return str(v)

    lines = [
        "## Volatility Regime Breakdown (per leg-trade)",
        "",
        _population_line(n_total),
        "",
        "Each row is one leg-trade (so a 2-leg basket records 2 rows per",
        "cycle). Win rate = share of leg-trades with r_multiple > 0.",
        "Share of leg-trades = per-regime exposure weight (denominator =",
        "classified leg-trades, i.e. excludes rows with null regime).",
        "",
        "| Regime | Leg-trades | Share of leg-trades | Win rate | Mean R | Median R | Mean PnL |",
        "|---|---|---|---|---|---|---|",
    ]
    has_r = "r_multiple" in df.columns
    has_pnl = "pnl_usd" in df.columns
    for v in regimes:
        sub = df[df["volatility_regime"] == v]
        n = len(sub)
        share = (n / n_classified * 100.0) if n_classified else 0.0
        if has_r:
            r_sub = sub["r_multiple"].dropna()
            wins = int((r_sub > 0).sum())
            wr = (wins / len(r_sub) * 100.0) if len(r_sub) else 0.0
            mean_r = float(r_sub.mean()) if len(r_sub) else 0.0
            med_r = float(r_sub.median()) if len(r_sub) else 0.0
        else:
            wr = mean_r = med_r = 0.0
        if has_pnl:
            p_sub = sub["pnl_usd"].dropna()
            mean_pnl = float(p_sub.mean()) if len(p_sub) else 0.0
        else:
            mean_pnl = 0.0
        lines.append(
            f"| {_regime_label(v)} | {n} | {share:.1f}% | {wr:.1f}% | "
            f"{mean_r:+.3f}R | {med_r:+.3f}R | {_fmt_money(mean_pnl)} |"
        )
    return "\n".join(lines)


def _build_leg_pnl_contribution(tl_df: pd.DataFrame) -> str:
    """Per-symbol leg-PnL contribution breakdown.

    Groups leg-trades by `symbol`, summing realized PnL per leg and
    showing each leg's share of the basket's total realized PnL.

    Pass-2 fix #3: adds Median PnL + Win Rate % columns.
    Pass-2 fix #6: prepends population line.
    Pass-2 fix #7: small-N guard suppresses when N < threshold.
    Pass-2 fix #8: sort by abs(total_realized) DESC (biggest contributors
    first regardless of sign).
    Pass-2 fix #9: column renamed to "Share of basket P&L" (ampersand) AND
    the share is a SIGNED contribution percentage so a losing leg in a
    losing basket shows NEGATIVE share, not a misleading positive
    percentage. Formula: share = leg_total / abs(basket_total) * 100
    (sign preserved from leg_total). A leg that bears more of the loss
    shows higher-magnitude negative share; a winning leg in a losing
    basket shows positive share with the basket's negative total
    explicitly noted in the caption.

    Returns empty string if pnl_usd missing or all-NaN.
    """
    if tl_df.empty or "pnl_usd" not in tl_df.columns or "symbol" not in tl_df.columns:
        return ""
    pn = tl_df["pnl_usd"].dropna()
    if pn.empty:
        return ""

    n_total = len(tl_df)
    if n_total < _SMALL_N_THRESHOLD:
        return _small_n_notice("Per-Leg PnL Contribution", n_total)

    df = tl_df.dropna(subset=["pnl_usd"]).copy()
    basket_total = float(df["pnl_usd"].sum())
    # Signed-share denominator: use |basket_total| so the sign of each
    # leg's contribution is preserved (fix #9). Falls back to 1.0 to
    # avoid divide-by-zero if every leg netted exactly 0.
    denom = abs(basket_total) if basket_total != 0 else 1.0
    grp = df.groupby("symbol", sort=False)

    rows = []
    for sym, sub in grp:
        n = len(sub)
        sum_pnl = float(sub["pnl_usd"].sum())
        mean_pnl = float(sub["pnl_usd"].mean()) if n else 0.0
        median_pnl = float(sub["pnl_usd"].median()) if n else 0.0
        win_rate = (float((sub["pnl_usd"] > 0).mean()) * 100.0) if n else 0.0
        # Signed share: preserves the sign of leg's contribution. A losing
        # leg in a losing basket shows negative share (its loss reduced
        # equity); a winning leg in a losing basket shows positive share.
        share = (sum_pnl / denom * 100.0) if denom else 0.0
        rows.append((sym, n, mean_pnl, median_pnl, win_rate, sum_pnl, share))
    # Sort by |total realized| descending — biggest contributors first.
    rows.sort(key=lambda r: -abs(r[5]))

    basket_total_note = (
        f"Basket total realized = {_fmt_money(basket_total)}"
        + ("  **(NEGATIVE — losing basket)**" if basket_total < 0 else "")
    )

    lines = [
        "## Per-Leg PnL Contribution",
        "",
        _population_line(n_total),
        "",
        "Realized PnL per leg symbol across all leg-trades. Sorted by",
        "|Total realized| descending. **Share of basket P&L** is signed",
        "and uses `|basket_total|` as denominator: a losing leg shows",
        "NEGATIVE share, a winning leg POSITIVE share, regardless of",
        "whether the basket itself was profitable. " + basket_total_note + ".",
        "",
        "| Symbol | Leg-trades | Mean PnL | Median PnL | Win Rate % | Total realized | Share of basket P&L |",
        "|---|---|---|---|---|---|---|",
    ]
    for sym, n, mean_pnl, median_pnl, win_rate, sum_pnl, share in rows:
        lines.append(
            f"| {sym} | {n} | {_fmt_money(mean_pnl)} | "
            f"{_fmt_money(median_pnl)} | {win_rate:.1f}% | "
            f"{_fmt_money(sum_pnl)} | {share:+.1f}% |"
        )
    return "\n".join(lines)


def _build_mfe_giveback_section(mfe: dict[str, Any]) -> str:
    """Per-cycle MFE / give-back distribution + capture-rate at exit.

    Quantifies how much unrealized profit each cycle peaked at and how
    much was surrendered before the exit signal fired. Rule-family
    agnostic; reads only `floating_total_usd` per cycle window.
    """
    cycles = mfe.get("cycles") or []
    if not cycles:
        return ""

    summary = mfe.get("summary") or {}
    by_tag = mfe.get("by_exit_tag") or {}
    profitable = mfe.get("profitable") or {}
    losing = mfe.get("losing") or {}
    hist = mfe.get("giveback_pct_histogram") or []
    capture_rate = mfe.get("capture_rate_pct", 0.0)
    gp = summary.get("giveback_pct_stats") or {}

    lines = [
        "## Cycle MFE / Give-back",
        "",
        "Per-cycle maximum favorable excursion (MFE = peak unrealized PnL",
        "reached during the cycle) versus the realized exit. Give-back =",
        "MFE − exit_floating; capture rate = exit_floating / MFE.",
        "Useful for spotting whether the exit signal harvests peaks (high",
        "capture) or rides cycles back down (low capture).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cycles analyzed | {summary.get('n_cycles', 0):,} |",
        f"| **Aggregate capture rate** (Σ exit / Σ MFE) | **{capture_rate:.1f}%** |",
        f"| Total unrealized peak (Σ MFE, clipped @ 0) | {_fmt_money(summary.get('total_mfe_usd', 0.0))} |",
        f"| Total realized at exit (Σ exit_floating) | {_fmt_money(summary.get('total_exit_floating', 0.0))} |",
        f"| Total give-back (Σ MFE − Σ exit) | {_fmt_money(summary.get('total_giveback_usd', 0.0))} |",
        f"| Mean per-cycle MFE | {_fmt_money(summary.get('mean_mfe_usd', 0.0))} |",
        f"| Median per-cycle MFE | {_fmt_money(summary.get('median_mfe_usd', 0.0))} |",
        f"| Mean per-cycle give-back ($) | {_fmt_money(summary.get('mean_giveback_usd', 0.0))} |",
        f"| Median per-cycle give-back ($) | {_fmt_money(summary.get('median_giveback_usd', 0.0))} |",
    ]
    if gp and gp.get("n", 0) > 0:
        lines.extend([
            f"| Give-back % — median | {gp['median']:.1f}% |",
            f"| Give-back % — p75 / p90 | {gp['p75']:.1f}% / {gp['p90']:.1f}% |",
        ])

    # By-exit-tag table — shows which exit kinds harvest vs leak.
    if by_tag:
        lines.extend([
            "",
            "### By exit tag",
            "",
            "| Exit tag | n | Mean MFE | Mean exit | Mean give-back | Capture % |",
            "|---|---|---|---|---|---|",
        ])
        for tag, d in sorted(by_tag.items(), key=lambda kv: -kv[1]["n"]):
            lines.append(
                f"| `{tag}` | {d['n']} | "
                f"{_fmt_money(d['mean_mfe_usd'])} | "
                f"{_fmt_money(d['mean_exit_floating'])} | "
                f"{_fmt_money(d['mean_giveback_usd'])} | "
                f"{d['capture_rate_pct']:.1f}% |"
            )

    # Profitable vs losing segmentation.
    if profitable.get("n", 0) > 0 or losing.get("n", 0) > 0:
        lines.extend([
            "",
            "### Profitable vs losing cycles",
            "",
            "| Segment | n | Mean MFE | Mean exit | Mean give-back | Capture % | Had MFE>0 | Never profitable |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for label, d in (("profitable (cycle_pnl > 0)", profitable),
                         ("losing (cycle_pnl ≤ 0)", losing)):
            if d.get("n", 0) == 0:
                lines.append(f"| {label} | 0 | — | — | — | — | — | — |")
                continue
            lines.append(
                f"| {label} | {d['n']} | "
                f"{_fmt_money(d['mean_mfe_usd'])} | "
                f"{_fmt_money(d['mean_exit_floating'])} | "
                f"{_fmt_money(d['mean_giveback_usd'])} | "
                f"{d['capture_rate_pct']:.1f}% | "
                f"{d.get('n_had_mfe_positive', 0)} | "
                f"{d.get('n_never_profitable', 0)} |"
            )

    # Give-back % histogram — quick visual of give-back distribution.
    if hist:
        max_count = max((b["count"] for b in hist), default=0)
        BAR_WIDTH = 30
        lines.extend([
            "",
            "### Give-back % distribution (cycles with MFE > 0)",
            "",
            "| Give-back % range | Count | Share | Distribution |",
            "|---|---|---|---|",
        ])
        for b in hist:
            bar_len = int(round(b["count"] / max_count * BAR_WIDTH)) if max_count else 0
            bar = "█" * bar_len
            lines.append(
                f"| {b['lo']:>3}–{b['hi']:>3}% | {b['count']} | "
                f"{b['share_pct']:.1f}% | `{bar}` |"
            )

    return "\n".join(lines)


def _build_time_and_capital_table(m: dict[str, Any]) -> str:
    """Time-in-position + capital-efficiency diagnostics. Signals whether
    capital is being deployed productively or sitting idle."""
    total = m.get("total_bars", 0)
    if not total:
        return ""
    in_pos = m.get("in_position_bars", 0)
    tip_pct = m.get("time_in_position_pct", 0.0)
    peak_notional = m.get("peak_notional_usd", 0.0)
    peak_eq = m.get("peak_equity_usd", 0.0)
    lev_ratio = m.get("peak_leverage_ratio", 0.0)
    recovery = m.get("recovery_bars")
    lines = [
        "## Time + Capital Telemetry",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total bars in window | {total:,} |",
        f"| Bars in position | {in_pos:,} |",
        f"| **Time in position** | **{tip_pct:.1f}%** |",
        f"| Peak notional exposure | {_fmt_money(peak_notional)} |",
        f"| Peak equity | {_fmt_money(peak_eq)} |",
        f"| **Peak leverage ratio** (peak_notional / peak_equity) | **{lev_ratio:.2f}×** |",
        f"| Recovery time from worst DD | {_fmt_bars(recovery)} |",
    ]
    return "\n".join(lines)


def _build_authority_note() -> str:
    """Explain that this is the authoritative file for cycle-mechanic baskets."""
    return (
        "## Authoritative source\n"
        "\n"
        "**This BASKET_REPORT.md is the authoritative artifact for\n"
        "cycle-mechanic baskets (H2_recycle@4/@5, H3_spread@1, future\n"
        "variants).** All numbers are computed by\n"
        "`tools.basket_hypothesis.canonical_metrics()` directly from\n"
        "the per-bar parquet ledger (`raw/results_basket_per_bar.parquet`).\n"
        "\n"
        "The legacy `REPORT_<directive>.md` is **no longer generated**\n"
        "for basket runs (suppressed 2026-05-18) because its trade-level\n"
        "lens missed every pyramid + liquidation event, producing\n"
        "misleading `Trades`, `Win Rate`, `Max DD`, `Profit Factor`\n"
        "values. Per-symbol per-strategy backtests still emit the\n"
        "legacy REPORT.md — only baskets are scope of the suppression.\n"
    )


def render_basket_report(
    parquet_path: str | Path,
    stake_usd: float,
    *,
    directive_id: str,
    rule_label: str,
    basket_id: str,
    timeframe: str,
    date_range: str,
    run_id: str | None = None,
    basket_csv_path: str | Path | None = None,
    tradelevel_csv_path: str | Path | None = None,
) -> str:
    """Render the BASKET_REPORT.md content for a basket run.

    Args mirror what the basket pipeline already knows when writing
    the legacy REPORT.md. Returns the rendered markdown string.

    Caller is responsible for writing to disk via `write_basket_report`
    (below) or directly.

    `tradelevel_csv_path` is optional; when provided and the file exists,
    three additional sections derived from per-leg-trade rows are emitted
    (R-multiple distribution, vol-regime breakdown, per-leg PnL share).
    """
    m = canonical_metrics(parquet_path, stake_usd, basket_csv_path=basket_csv_path)
    mfe = compute_mfe_giveback(parquet_path, rule_family=m.get("rule_family"))
    if tradelevel_csv_path and Path(tradelevel_csv_path).is_file():
        tl_df = pd.read_csv(tradelevel_csv_path)
    else:
        tl_df = pd.DataFrame()

    header = [
        f"# Basket Report (cycle-aware) — {directive_id}",
        "",
        f"Run ID: `{run_id}`" if run_id else "Run ID: (not specified)",
        f"Basket ID: `{basket_id}`",
        f"Recycle Rule: `{rule_label}`  ({_rule_family_label(m['rule_family'])})",
        f"Timeframe: {timeframe}",
        f"Date Range: {date_range}",
        f"Generated by: `tools.basket_hypothesis.basket_report`",
        "",
        "---",
        "",
    ]

    # Pass-2 fix #4: Per-Leg PnL Contribution promoted to immediately
    # below Top-Line Metrics. Operator's natural reading order is
    # "net % -> DD % -> Ret/DD -> which leg made the money?" so the
    # per-leg view should land before Event Taxonomy / Cycle Breakdown.
    sections = [
        _build_top_line_table(m),
        _build_leg_pnl_contribution(tl_df),       # promoted (pass-2 fix #4)
        _build_event_taxonomy_table(m),
        _build_time_and_capital_table(m),
        _build_underwater_section(m),
        _build_cycle_breakdown_table(m),
        _build_pnl_histogram_table(m),
        _build_r_multiple_histogram(tl_df),
        _build_vol_regime_breakdown(tl_df),
        _build_mfe_giveback_section(mfe),
        _build_monthly_curve_table(m),
        _build_asymmetry_table(m),
        _build_peak_lots_table(m),
        _build_authority_note(),
    ]
    body = "\n\n".join(s for s in sections if s)
    return "\n".join(header) + body + "\n"


def write_basket_report(
    out_dir: str | Path,
    parquet_path: str | Path,
    stake_usd: float,
    *,
    directive_id: str,
    rule_label: str,
    basket_id: str,
    timeframe: str,
    date_range: str,
    run_id: str | None = None,
    basket_csv_path: str | Path | None = None,
    tradelevel_csv_path: str | Path | None = None,
) -> Path:
    """Render + write BASKET_REPORT_<directive_id>.md to out_dir.

    Returns the path written.

    If `tradelevel_csv_path` is not provided, it is derived from the
    parquet path's parent dir (`<parquet_parent>/results_tradelevel.csv`)
    so callers that already know the parquet location don't need to
    pass the sibling CSV explicitly.
    """
    parquet_path = Path(parquet_path)
    if tradelevel_csv_path is None:
        candidate = parquet_path.parent / "results_tradelevel.csv"
        tradelevel_csv_path = candidate if candidate.is_file() else None
    content = render_basket_report(
        parquet_path, stake_usd,
        directive_id=directive_id, rule_label=rule_label,
        basket_id=basket_id, timeframe=timeframe, date_range=date_range,
        run_id=run_id, basket_csv_path=basket_csv_path,
        tradelevel_csv_path=tradelevel_csv_path,
    )
    out_dir = Path(out_dir)
    out_path = out_dir / f"BASKET_REPORT_{directive_id}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


__all__ = ["render_basket_report", "write_basket_report"]
