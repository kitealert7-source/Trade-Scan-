"""
Robustness Report Formatter.
Takes the structured results dictionary from runner.py and generates exactly
the same Markdown report as the legacy evaluate_robustness.py script.
"""
from datetime import datetime
import pandas as pd


def _fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


from tools.robustness import __version__

def format_report(
    results: dict, 
    prefix: str, 
    profile: str, 
    timestamp: str | None = None
) -> str:
    """Generate full markdown report from results dict."""
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    out = [f"# ROBUSTNESS REPORT — {prefix} / {profile}\n"]
    
    # Engine signature added per Phase 5 Governance
    out.append(f"Engine: Robustness v{__version__} | Generated: {timestamp}\n")

    out.append("## Section 1 — Edge Metrics Summary\n")
    em = results.get("edge_metrics", {})
    
    out.append(f"| Metric | Value |")
    out.append(f"|---|---|")
    out.append(f"| Total Trades | {em.get('total_trades', 0)} |")
    out.append(f"| Win Rate | {em.get('win_rate', 0):.1f}% |")
    out.append(f"| Avg Win | {_fmt_usd(em.get('avg_win', 0))} |")
    out.append(f"| Avg Loss | {_fmt_usd(em.get('avg_loss', 0))} |")
    out.append(f"| Payoff Ratio | {em.get('payoff_ratio', 0):.2f} |")
    out.append(f"| Expectancy / Trade | {_fmt_usd(em.get('expectancy_per_trade', 0))} |")
    out.append(f"| Profit Factor | {em.get('profit_factor', 0):.2f} |")
    out.append(f"| Net Profit | {_fmt_usd(em.get('net_profit', 0))} |")
    out.append(f"| Max DD (USD) | {_fmt_usd(em.get('max_dd_usd', 0))} |")
    out.append(f"| Recovery Factor | {em.get('recovery_factor', 0):.2f} |")
    out.append("")

    # Section 2 & 3: Tail
    tc = results.get("tail_contribution", {})
    out.append("## Section 2 — Tail Contribution\n")
    out.append(f"- Top 1 trade: {tc.get('top_1', 0):.2%}")
    out.append(f"- Top 5 trades: {tc.get('top_5', 0):.2%}")
    out.append(f"- Top 1% ({tc.get('n_1pct', 0)}): {tc.get('top_1pct', 0):.2%}")
    out.append(f"- Top 5% ({tc.get('n_5pct', 0)}): {tc.get('top_5pct', 0):.2%}")
    out.append(f"- Total PnL: {_fmt_usd(tc.get('total_pnl', 0))}\n")

    tr_results = results.get("tail_removal", [])
    out.append("## Section 3 — Tail Removal\n")
    for tr_res in tr_results:
        pct = tr_res.get("pct_cutoff", 0.05)
        label = f"Top {int(pct*100)}%"
        out.append(f"**Removing {label} ({tr_res.get('removed_count', 0)} trades)**")
        out.append(f"- Original CAGR: {_fmt_pct(tr_res.get('original_cagr', 0) * 100)}")
        out.append(f"- New CAGR: {_fmt_pct(tr_res.get('new_cagr', 0) * 100)}")
        out.append(f"- Degradation: {_fmt_pct(tr_res.get('degradation_pct', 0))}")
        out.append(f"- New Equity: {_fmt_usd(tr_res.get('new_equity', 0))}\n")

    # Section 4: Sequence MC
    mc = results.get("sequence_mc", {})
    out.append("## Section 4 — Sequence Monte Carlo (500 runs)\n")
    out.append(f"- Mean CAGR: {_fmt_pct(mc.get('mean_cagr', 0))}") # Note: mean_cagr not collected in runner, need an update
    out.append(f"- Median CAGR: {_fmt_pct(mc.get('median_cagr', 0))}")
    out.append(f"- 5th pctl CAGR: {_fmt_pct(mc.get('p5_cagr', 0))}")
    out.append(f"- 95th pctl CAGR: {_fmt_pct(mc.get('p95_cagr', 0))}")
    out.append(f"- Mean DD: {_fmt_pct(mc.get('mean_dd', 0))}")     # Note: mean_dd not collected in runner
    out.append(f"- 95th pctl DD: {_fmt_pct(mc.get('p95_dd', 0))}")
    out.append(f"- Blow-up runs (>90% DD): {mc.get('blowup_runs', 0)}\n")

    out.append("## Section 5 — Reverse Path Test\n")
    rev = results.get("reverse_path", {})
    out.append(f"- Final Equity: {_fmt_usd(rev.get('final_equity', 0))}")
    out.append(f"- CAGR: {_fmt_pct(rev.get('cagr', 0) * 100)}")
    out.append(f"- Max DD: {_fmt_pct(rev.get('max_dd_pct', 0))}")
    out.append(f"- Max Loss Streak: {rev.get('max_loss_streak', 0)}\n")

    # Section 6: Rolling 1-Year
    out.append("## Section 6 — Rolling 1-Year Window\n")
    rol = results.get("rolling", {})
    stab = rol.get("stability", {})
    out.append(f"- Total windows: {stab.get('total_windows', 0)}")
    out.append(f"- Negative windows: {stab.get('negative_windows', 0)}")
    out.append(f"- Return < -10%: {stab.get('ret_under_minus_10', 0)}")
    out.append(f"- DD > 15%: {stab.get('dd_over_15', 0)}")
    out.append(f"- DD > 20%: {stab.get('dd_over_20', 0)}")
    out.append(f"- Worst return: {_fmt_pct(stab.get('worst_return', 0))}")
    out.append(f"- Worst DD: {_fmt_pct(stab.get('worst_dd', 0))}")
    out.append(f"- Mean return: {_fmt_pct(stab.get('mean_return', 0))}")
    out.append(f"- Mean DD: {_fmt_pct(stab.get('mean_dd', 0))}")
    out.append(f"- Negative clustering: {stab.get('clustering', 'N/A')}\n")

    out.append("### Year-Wise PnL\n")
    out.append("| Year | Trades | Net PnL | Win Rate | Avg PnL |")
    out.append("|---|---|---|---|---|")
    
    yw = results.get("year_wise_pnl", {})
    # Need to sort keys as strings
    for yr in sorted(yw.keys(), key=lambda x: int(x)):
        d = yw[yr]
        out.append(f"| {yr} | {d['trades']} | {_fmt_usd(d['net_pnl'])} | {d['win_rate']:.1f}% | {_fmt_usd(d['avg_pnl'])} |")
    out.append("")

    out.append("### Monthly PnL Heatmap\n")
    hm = results.get("monthly_heatmap", {})
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    # Collect all months present across all years
    all_months = set()
    for yr, m_dict in hm.items():
        all_months.update([int(m) for m in m_dict.keys()])
    sorted_months = sorted(list(all_months))
    
    if sorted_months:
        header_cols = [month_names[m - 1] for m in sorted_months]
        out.append("| Year | " + " | ".join(header_cols) + " |")
        out.append("|---" + "|---" * len(header_cols) + "|")
        for yr in sorted(hm.keys(), key=lambda x: int(x)):
            cells = []
            for m in sorted_months:
                v = hm[yr].get(str(m), hm[yr].get(m, 0.0))
                cells.append(f"{v:+.0f}")
            out.append(f"| {yr} | " + " | ".join(cells) + " |")
    out.append("")

    # Section 7: Drawdown
    out.append("## Section 7 — Drawdown Diagnostics\n")
    for i, cl in enumerate(results.get("drawdown", [])):
        rec = cl.get("recovery_date")
        if pd.isna(rec):
            rec_str = "ONGOING"
        else:
            rec_str = str(rec).split("T")[0].split(" ")[0]
        
        start = str(cl.get("start_date", "")).split("T")[0].split(" ")[0]
        trough = str(cl.get("trough_date", "")).split("T")[0].split(" ")[0]
        
        out.append(f"### Cluster {i + 1}")
        out.append(f"- Start: {start}")
        out.append(f"- Trough: {trough}")
        out.append(f"- Recovery: {rec_str}")
        out.append(f"- Max DD: {_fmt_pct(cl.get('max_dd_pct', 0))}")
        out.append(f"- Duration: {cl.get('duration_days', 0)} days")

        exp = cl.get("exposure", {})
        out.append(f"- Trades open: {exp.get('total_trades', 0)}")
        out.append(f"- Long/Short: {exp.get('pct_long', 0):.1f}% / {exp.get('pct_short', 0):.1f}%")
        out.append(f"- Top-2 symbol concentration: {exp.get('symbol_concentration_top2', 0):.1f}%")

        beh = cl.get("behavior", {})
        tc = beh.get('trades_closed', 0)
        out.append(f"- Trades closed in plunge: {tc}")
        if tc > 0:
            out.append(f"- Win rate: {beh.get('win_rate', 0):.1f}%")
            out.append(f"- Avg PnL: {_fmt_usd(beh.get('avg_pnl', 0))}")
            out.append(f"- Max loss streak: {beh.get('max_loss_streak', 0)}")
        out.append("")

    # Section 8: Streaks
    strks = results.get("streaks", {})
    out.append("## Section 8 — Streak Analysis\n")
    out.append(f"| Metric | Wins | Losses |")
    out.append(f"|---|---|---|")
    out.append(f"| Max Streak | {strks.get('max_win_streak', 0)} | {strks.get('max_loss_streak', 0)} |")
    out.append(f"| Avg Streak | {strks.get('avg_win_streak', 0):.1f} | {strks.get('avg_loss_streak', 0):.1f} |")
    out.append("")

    # Section 9: Friction
    out.append("## Section 9 — Friction Stress Test\n")
    out.append("| Scenario | Net Profit | PF | Degradation |")
    out.append("|---|---|---|---|")
    for r in results.get("friction", []):
        out.append(f"| {r.get('scenario')} | {_fmt_usd(r.get('net_profit', 0))} | {r.get('pf', 0):.2f} | {_fmt_pct(r.get('degradation_pct', 0))} |")
    out.append("")

    # Section 10: Directional
    dr = results.get("directional", {})
    out.append("## Section 10 — Directional Robustness\n")
    out.append(f"- Total Longs: {dr.get('n_longs', 0)}")
    out.append(f"- Total Shorts: {dr.get('n_shorts', 0)}")
    out.append(f"- Baseline PF: {dr.get('baseline_pf', 0):.2f}")
    out.append(f"- No Top-20 Longs PF: {dr.get('no_long20_pf', 0):.2f}")
    out.append(f"- No Top-20 Shorts PF: {dr.get('no_short20_pf', 0):.2f}")
    out.append(f"- No Both PF: {dr.get('no_both_pf', 0):.2f}\n")

    # Section 11: Early/Late
    el = results.get("early_late", {})
    out.append("## Section 11 — Early/Late Split\n")
    for label, key in [("First Half", "first_half"), ("Second Half", "second_half")]:
        data = el.get(key, {})
        out.append(f"**{label}** ({data.get('trade_count', 0)} trades)")
        out.append(f"- CAGR: {_fmt_pct(data.get('cagr', 0) * 100)}")
        out.append(f"- Max DD: {_fmt_pct(data.get('max_dd_pct', 0))}")
        out.append(f"- Win Rate: {_fmt_pct(data.get('win_rate', 0))}\n")

    # Section 12: Symbol Isolation
    iso = results.get("symbol_isolation", [])
    out.append("## Section 12 — Symbol Isolation Stress\n")
    if isinstance(iso, dict) and "note" in iso:
        pass
    else:
        out.append("| Removed | Remaining | CAGR | Max DD |")
        out.append("|---|---|---|---|")
        for r in iso:
            out.append(f"| {r.get('removed_symbol')} | {r.get('remaining_trades', 0)} | {_fmt_pct(r.get('cagr', 0) * 100)} | {_fmt_pct(r.get('max_dd_pct', 0))} |")
        out.append("")

    # Section 13: Symbol Breakdown
    sb = results.get("symbol_breakdown", {})
    out.append("## Section 13 — Per-Symbol PnL Breakdown\n")
    out.append("| Symbol | Trades | Net PnL | Win Rate | % Contribution |")
    out.append("|---|---|---|---|---|")
    total_net = sum([d.get('pnl', 0) for d in sb.values()])
    rows = []
    for sym, d in sb.items():
        n = d.get('trades', 0)
        net = d.get('pnl', 0)
        wr = d.get('win_rate', d.get('win_rate_calc', 0))
        pct = (net / total_net * 100) if total_net != 0 else 0
        rows.append((sym, n, net, wr, pct))
    rows.sort(key=lambda x: x[2], reverse=True)
    for sym, n, net, wr, pct in rows:
        out.append(f"| {sym} | {n} | {_fmt_usd(net)} | {wr:.1f}% | {pct:+.1f}% |")
    out.append("")

    # Section 14: Block Bootstrap
    bb = results.get("block_bootstrap", {})
    if bb:
        out.append("## Section 14 — Block Bootstrap (100 runs)\n")
        if "error" in bb:
            out.append(f"- [SKIPPED] Block bootstrap failed: {bb['error']}\n")
        else:
            out.append(f"- Mean CAGR: {_fmt_pct(bb.get('mean_cagr', 0))}")
            out.append(f"- Median CAGR: {_fmt_pct(bb.get('median_cagr', 0))}")
            out.append(f"- 5th pctl CAGR: {_fmt_pct(bb.get('p5_cagr', 0))}")
            out.append(f"- 95th pctl CAGR: {_fmt_pct(bb.get('p95_cagr', 0))}")
            out.append(f"- Mean DD: {_fmt_pct(bb.get('mean_dd', 0))}")
            out.append(f"- Worst DD: {_fmt_pct(bb.get('worst_dd', 0))}")
            out.append(f"- Runs ending below start: {bb.get('under_start', 0)}\n")

    # Section 15 & 16: Seasonality
    def _format_season(res, title):
        mode = res.get("mode", "SHORT")
        out.append(f"## {title} [{mode} MODE]\n")
        
        if res.get("suppressed"):
            out.append(f"- SUPPRESSED: {res.get('suppression_reason', 'Threshold failed')}")
            disp = res.get('dispersion', {})
            out.append(f"- Dispersion: max deviation {disp.get('max_deviation', 0):.2f} from global mean {disp.get('global_mean', 0):.2f}\n")
            return
            
        out.append(f"**Verdict:** {res.get('verdict', 'N/A')}")
        out.append(f"- Kruskal-Wallis H: {res.get('test_statistic', 0):.2f}")
        if 'p_value' in res:
            out.append(f"- Kruskal-Wallis p-value: {res['p_value']:.4f}")
        out.append(f"- Effect size (\u03b7\u00b2): {res.get('effect_size', 0):.4f}\n")
        
        buckets = res.get("buckets", [])
        if buckets:
            # Check if stability was tested
            show_stab = any(b.get("stable") is cn for b in buckets for cn in [True, False])
            
            header = "| Bucket | Trades | Net PnL | PF | Flag |"
            sep = "|---|---|---|---|---|"
            if show_stab:
                header += " Stable |"
                sep += "---|"
            out.append(header)
            out.append(sep)
            
            for b in buckets:
                b_name = str(b.get("month", b.get("weekday", b.get("time_col", "?"))))
                flg = "⚠️" if b.get("flag") else "—"
                row = f"| {b_name} | {b.get('trades', 0)} | {_fmt_usd(b.get('pnl', 0))} | {b.get('pf', 0):.2f} | {flg} |"
                if show_stab:
                    stb = "✅" if b.get("stable") else ("❌" if b.get("stable") is False else "—")
                    row += f" {stb} |"
                out.append(row)
            out.append("")
            
        decs = res.get("exposure_decisions")
        if decs:
            out.append("**Exposure Recommendations:**")
            for d in decs:
                b_name = d.get("month", d.get("weekday", d.get("time_col", "?")))
                out.append(f"- Bucket {b_name}: {d.get('action')} (PF: {d.get('pf', 0):.2f})")
            out.append("")

    if "monthly_seasonality" in results:
        _format_season(results["monthly_seasonality"], "Section 15 — Monthly Seasonality")
    if "weekday_seasonality" in results:
        _format_season(results["weekday_seasonality"], "Section 16 — Weekday Seasonality")

    return "\n".join(out)
