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
    detected rule family to keep the table tight."""
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
        total_liq = ev["h3_liq_time"] + ev["h3_liq_adverse"] + ev["h3_liq_reverse"] + n_trail
        lines.extend([
            "| Event | Count | Notes |",
            "|---|---|---|",
            f"| Pyramids (add to both legs) | {_fmt_int(ev['h3_pyramids'])} | anti-Martingale add when basket P&L crosses threshold |",
            f"| Liquidations — TIME stop | {_fmt_int(ev['h3_liq_time'])} | basket aged out of position window |",
            f"| Liquidations — ADVERSE stop | {_fmt_int(ev['h3_liq_adverse'])} | basket P&L below adverse threshold |",
            f"| Liquidations — TRAIL stop | {_fmt_int(n_trail)} | peak-relative retracement after running peak armed |",
            f"| Liquidations — REVERSE cross | {_fmt_int(ev['h3_liq_reverse'])} | regime-flip detected via cross_side inversion |",
            f"| Liquidations (total) | {_fmt_int(total_liq)} | sum of above four |",
            f"| Holding bars (in position) | {_fmt_int(ev['h3_holding'])} | basket open + waiting for trigger |",
            f"| Awaiting-entry bars | {_fmt_int(ev['h3_awaiting'])} | flat, waiting for next cross signal |",
        ])
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
    hint at."""
    hist = m.get("pnl_histogram") or []
    if not hist:
        return ""
    max_count = max(b["count"] for b in hist) if hist else 0
    BAR_WIDTH = 30  # max ASCII bar width
    lines = [
        "## Cycle-PnL Distribution",
        "",
        "Seven adaptive buckets (quantile-based) across the observed",
        "cycle-PnL range. The ASCII bar shows relative cycle counts.",
        "",
        "| PnL range (USD) | Count | Share | Distribution |",
        "|---|---|---|---|",
    ]
    for b in hist:
        bar_len = int(round(b["count"] / max_count * BAR_WIDTH)) if max_count else 0
        bar = "█" * bar_len
        lines.append(
            f"| {_fmt_money(b['lo'])} → {_fmt_money(b['hi'])} | "
            f"{b['count']} | {b['share_pct']:.1f}% | `{bar}` |"
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
) -> str:
    """Render the BASKET_REPORT.md content for a basket run.

    Args mirror what the basket pipeline already knows when writing
    the legacy REPORT.md. Returns the rendered markdown string.

    Caller is responsible for writing to disk via `write_basket_report`
    (below) or directly.
    """
    m = canonical_metrics(parquet_path, stake_usd, basket_csv_path=basket_csv_path)

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

    sections = [
        _build_top_line_table(m),
        _build_event_taxonomy_table(m),
        _build_time_and_capital_table(m),
        _build_underwater_section(m),
        _build_cycle_breakdown_table(m),
        _build_pnl_histogram_table(m),
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
) -> Path:
    """Render + write BASKET_REPORT_<directive_id>.md to out_dir.

    Returns the path written.
    """
    content = render_basket_report(
        parquet_path, stake_usd,
        directive_id=directive_id, rule_label=rule_label,
        basket_id=basket_id, timeframe=timeframe, date_range=date_range,
        run_id=run_id, basket_csv_path=basket_csv_path,
    )
    out_dir = Path(out_dir)
    out_path = out_dir / f"BASKET_REPORT_{directive_id}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


__all__ = ["render_basket_report", "write_basket_report"]
