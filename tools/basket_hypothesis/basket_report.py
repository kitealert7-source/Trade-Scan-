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
    }.get(rf, rf)


def _build_top_line_table(m: dict[str, Any]) -> str:
    """Top-line metrics: net%, DD%, ret/DD, equity, exit."""
    final_eq = m["final_equity_usd"]
    stake = m["stake_usd"]
    lines = [
        "## Top-Line Metrics (canonical — parquet-derived)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stake (initial) | {_fmt_money(stake)} |",
        f"| Final equity | {_fmt_money(final_eq)} |",
        f"| Net PnL | {_fmt_money(final_eq - stake)} |",
        f"| **Net %** | **{_fmt_pct(m['net_pct'])}** |",
        f"| Max DD (USD) | {_fmt_money(-m['max_dd_usd'])} |",
        f"| **Max DD %** | **{_fmt_pct(-m['max_dd_pct'])}** |",
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
    return "\n".join(lines)


def _build_cycle_breakdown_table(m: dict[str, Any]) -> str:
    """Per-cycle PnL distribution + win rate. Only meaningful for cycle
    mechanics."""
    if m["rule_family"] == "v1_recycle":
        return ""  # not applicable
    rec = m["cycles_completed"]
    if rec == 0:
        return "## Cycle Breakdown\n\n(no liquidation events — basket ran continuously)\n"
    pnls = [c["cycle_pnl_usd"] for c in m["cycle_pnls"]]
    pnl_s = pd.Series(pnls) if pnls else pd.Series(dtype=float)
    lines = [
        "## Cycle Breakdown (reconstructed from per-bar realized_total deltas)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cycles completed | {rec} |",
        f"| Cycles won (PnL > 0) | {m['cycles_won']} |",
        f"| Cycles lost (PnL < 0) | {m['cycles_lost']} |",
        f"| **Cycle win rate** | **{m['cycle_win_rate_pct']:.1f}%** |",
        f"| Median cycle PnL | {_fmt_money(m['median_cycle_pnl'])} |",
        f"| Mean cycle PnL | {_fmt_money(m['mean_cycle_pnl'])} |",
        f"| Best cycle | {_fmt_money(pnl_s.max() if len(pnl_s) else 0)} |",
        f"| Worst cycle | {_fmt_money(pnl_s.min() if len(pnl_s) else 0)} |",
    ]
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
    lines = [
        "## Per-Leg Peak Lot Exposure",
        "",
        "Largest lot held on each leg during the run. For pyramid",
        "mechanics, this measures the largest single-bar exposure",
        "the strategy held — informs capital sizing decisions.",
        "",
        "| Symbol | Peak lot |",
        "|---|---|",
    ]
    for sym, lot in pl.items():
        lines.append(f"| {sym} | {lot:.3f} |")
    return "\n".join(lines)


def _build_legacy_caveat() -> str:
    """Explain why this file exists alongside the legacy REPORT.md."""
    return (
        "## Why this file exists (legacy REPORT.md caveat)\n"
        "\n"
        "The legacy `REPORT_<directive>.md` (in the same folder) was\n"
        "designed for classic entry-exit strategies and counts only\n"
        "events recorded in `results_tradelevel.csv`. For cycle-mechanic\n"
        "rules (H2_recycle@4 bump-and-liquidate, @5 pyramid-and-liquidate,\n"
        "future variants), the cycle events (pyramids, liquidations) are\n"
        "NOT in the trade-level table — they live in `recycle_events` and\n"
        "the per-bar parquet ledger. Consequently, the legacy report's\n"
        "`Trades`, `Win Rate`, `Max DD`, and `Profit Factor` fields are\n"
        "misleading for these rule families (typically showing only the\n"
        "residual DATA_END force-close trades).\n"
        "\n"
        "**This BASKET_REPORT.md is authoritative for cycle-mechanic\n"
        "baskets.** All numbers here are computed by\n"
        "`tools.basket_hypothesis.canonical_metrics()` from the per-bar\n"
        "parquet — the source of truth.\n"
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
        _build_cycle_breakdown_table(m),
        _build_asymmetry_table(m),
        _build_peak_lots_table(m),
        _build_legacy_caveat(),
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
