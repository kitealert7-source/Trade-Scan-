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

    out.append("---\n")
    out.append("## Execution Profile & Assumptions\n")
    out.append(f"> **Note:** The metrics calculated in this robustness report are based on the **{profile}** capital allocation profile. ")
    out.append("> They reflect the combined trades **AFTER dynamic position sizing has been applied** by the capital wrapper.\n")
    out.append("---\n")

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

    # Section 4: Regime-Aware Block Bootstrap MC
    mc = results.get("regime_block_mc", results.get("sequence_mc", {}))
    out.append("## Section 4 — Monte Carlo Simulation\n")
    mc_method = mc.get("mc_method", "RANDOM_SHUFFLE")
    out.append(f"- Method: **{mc_method}**")
    if mc_method == "REGIME_AWARE_BLOCK_BOOTSTRAP":
        out.append(f"- Block Definition: {mc.get('block_definition', 'N/A')}")
        out.append(f"- Total Regime Blocks: {mc.get('total_blocks', 'N/A')}")
        regime_dist = mc.get("regime_distribution", {})
        if regime_dist:
            dist_str = ", ".join(f"{k}: {v}" for k, v in sorted(regime_dist.items()))
            out.append(f"- Regime Distribution: {dist_str}")
    out.append(f"- Simulations: {mc.get('iterations', 500)}")
    out.append(f"- Seed: {mc.get('seed', 42)}\n")
    out.append(f"- Mean CAGR: {_fmt_pct(mc.get('mean_cagr', 0) * 100)}")
    out.append(f"- Median CAGR: {_fmt_pct(mc.get('median_cagr', 0) * 100)}")
    out.append(f"- 5th pctl CAGR: {_fmt_pct(mc.get('p5_cagr', 0) * 100)}")
    out.append(f"- 95th pctl CAGR: {_fmt_pct(mc.get('p95_cagr', 0) * 100)}")
    out.append(f"- Mean DD: {_fmt_pct(mc.get('mean_dd', 0))}")
    out.append(f"- 95th pctl DD: {_fmt_pct(mc.get('p95_dd', 0))}")
    out.append(f"- Blow-up runs (>90% DD): {mc.get('blowup_runs', 0)}\n")

    # Section 4.5: Position Sizing Guidance
    ps = results.get("position_sizing", {})
    if ps:
        out.append("## Section 4.5 — Position Sizing Guidance\n")
        out.append(f"Current capital model risk assumption: {_fmt_pct(ps.get('current_risk_pct', 0))}\n")
        out.append("**Monte Carlo Drawdown Distribution**")
        out.append(f"- 95th pctl DD: {_fmt_pct(ps.get('mc_dd_95', 0))}\n")
        out.append("**Suggested Risk Levels**\n")
        out.append("| Target Max DD | Suggested Risk |")
        out.append("|---|---|")
        for row in ps.get("sizing_table", []):
            out.append(f"| {_fmt_pct(row['target_max_dd'])} | {_fmt_pct(row['suggested_risk_pct'])} |")
        out.append("")
        out.append("**Kelly Fraction**\n")
        out.append(f"- Full Kelly: {ps.get('kelly_fraction', 0):.4f}")
        out.append(f"- Safe fraction (½ Kelly): {ps.get('kelly_safe_fraction', 0):.4f}\n")

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

    # Section 9: Friction Stress Test (slippage only — spread already in OHLC)
    tiered = results.get("friction_tiered", {})
    config_src = tiered.get("config_source", "unknown")
    out.append(f"## Section 9 — Friction Stress Test (Slippage Only)\n")
    out.append(f"> Cost model: `{config_src}` | Spread already in OHLC prices — only slippage modeled\n")
    out.append("| Scenario | Slippage (pips/side) | Net Profit | PF | Degradation | Avg Cost/Trade |")
    out.append("|---|---|---|---|---|---|")
    for r in results.get("friction", []):
        slip = r.get("slippage_pips", 0.0)
        avg_cost = r.get("avg_friction_cost", 0.0)
        out.append(
            f"| {r.get('scenario')} | {slip:.1f} "
            f"| {_fmt_usd(r.get('net_profit', 0))} | {r.get('pf', 0):.2f} "
            f"| {_fmt_pct(r.get('degradation_pct', 0))} | {_fmt_usd(avg_cost)} |"
        )
    out.append("")

    # Tier-by-tier PnL survival check
    tiers = tiered.get("tiers", {})
    if tiers:
        base_tier = tiers.get("baseline", {})
        extreme_tier = tiers.get("extreme", {})
        if base_tier and extreme_tier:
            base_pf = base_tier.get("pf", 0)
            extreme_pf = extreme_tier.get("pf", 0)
            if extreme_pf >= 1.0:
                out.append("> **PASS**: Strategy survives even extreme slippage.\n")
            elif base_pf >= 1.0:
                out.append("> **CAUTION**: Profitable under baseline slippage but breaks under extreme.\n")
            else:
                out.append("> **FAIL**: Unprofitable even under baseline slippage.\n")

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

    # ── Section 17: Capital Efficiency Summary + Baseline Comparison ──────────
    ce = results.get("capital_efficiency")
    if ce:
        out.append("## Section 17 — Capital Efficiency Summary\n")

        src = " *(recomputed)*" if ce.get("capital_source") == "recomputed" else ""
        rouc = ce["return_on_utilized_capital"]
        out.append("| Metric | Value |")
        out.append("|---|---|")
        out.append(f"| Utilized Capital{src} | {_fmt_usd(ce['utilized_capital'])} |")
        out.append(f"| Net PnL | {_fmt_usd(ce['net_pnl'])} |")
        out.append(f"| Return on Utilized Capital | {rouc:.4f} ({rouc * 100:.2f}%) |")
        out.append(f"| Utilization (%) | {ce['utilization_pct']:.2f}% |")
        out.append(f"| Profit Factor | {ce['profit_factor']:.2f} |")
        out.append(f"| Total Trades | {ce['total_trades']} |")
        out.append(f"| Stability Factor (min(1, PF/2)) | {ce['stability_factor']:.4f} |")
        out.append(f"| Sample Factor (ln(1+N)) | {ce['sample_factor']:.4f} |")
        out.append(f"| **Efficiency Score** | **{ce['efficiency_score']:.4f}** |")
        out.append("")

        # Baseline comparison block
        bc = ce.get("baseline_comparison")
        if bc:
            out.append(f"### Baseline Comparison — {bc['baseline_key']}\n")
            out.append(f"| Metric | {bc['baseline_key']} (Baseline) | {bc['current_key']} |")
            out.append("|---|---|---|")
            out.append(f"| Realized PnL | {_fmt_usd(bc['baseline_pnl'])} | {_fmt_usd(bc['current_pnl'])} |")
            out.append(f"| Return on Utilized Capital | {bc['baseline_rouc']:.4f} | {bc['current_rouc']:.4f} |")
            out.append(f"| Utilization % | {bc['baseline_util_pct']:.2f}% | {bc['current_util_pct']:.2f}% |")
            out.append(f"| Max DD % | {bc['baseline_max_dd_pct']:.2f}% | {bc['current_max_dd_pct']:.2f}% |")
            out.append("")

            pnl_mult  = bc.get("pnl_multiplier")
            util_mult = bc.get("utilization_multiplier")
            edge_dlt  = bc["edge_delta"]
            out.append(f"- PnL Multiplier: {'N/A' if pnl_mult  is None else f'{pnl_mult:.2f}×'}")
            out.append(f"- Utilization Multiplier: {'N/A' if util_mult is None else f'{util_mult:.2f}×'}")
            out.append(f"- Edge Delta (RoUC): {edge_dlt:+.4f}")
            out.append("")

            driver_map = {
                "utilization":       "primarily driven by utilization",
                "edge improvement":  "primarily driven by edge improvement",
                "both":              "driven by both utilization and edge improvement",
            }
            driver_label = driver_map.get(bc["driver"], bc["driver"])
            out.append(f"> Scaling impact: PnL increase is {driver_label}.\n")

        # Per-engine ranking (PF_ composite portfolios only)
        engine_rows = ce.get("engine_ranking", [])
        if engine_rows:
            out.append("### Per-Engine Efficiency Ranking\n")
            out.append("> **Note:** `Return Proxy / $1K` = net_pnl / $1,000. "
                       "Proxy metric — per-engine utilized capital not available. "
                       "Do not compare directly to portfolio-level RoUC.\n")
            out.append("| Rank | Strategy | Symbol | Trades | Net PnL | Return Proxy / $1K | PF | Efficiency Score |")
            out.append("|---|---|---|---|---|---|---|---|")
            for i, row in enumerate(engine_rows, 1):
                out.append(
                    f"| {i} | {row['strategy_id']} | {row['symbol']} | {row['trades']} | "
                    f"{_fmt_usd(row['net_pnl'])} | {row['return_proxy_per_1000']:.4f} | "
                    f"{row['pf']:.2f} | {row['efficiency_score']:.4f} |"
                )
            out.append("")

    # ── Section 18: Edge Quality Gate ──
    eqg = results.get("edge_quality_gate")
    if eqg:
        out.append("## 18. Edge Quality Gate\n")
        out.append("> Industry-calibrated individual edge assessment. "
                   "Sources: Harvey/Liu/Zhu (2016), Lopez de Prado (2018), "
                   "Van Tharp (2006), Kaufman (2013), Pardo (2008).\n")

        # t-statistic block
        out.append("### Statistical Significance\n")
        out.append(f"| Metric | Value |")
        out.append(f"|--------|-------|")
        out.append(f"| t-statistic (SQN) | **{eqg['t_stat']:.2f}** |")
        out.append(f"| IR (per-trade) | {eqg['ir_per_trade']:.4f} |")
        out.append(f"| Trades needed for t=2.0 | {eqg['trades_needed_t2']:.0f} |")
        out.append(f"| Trades needed for t=3.0 | {eqg['trades_needed_t3']:.0f} |")
        out.append(f"| Verdict | **{eqg['t_verdict']}** |")
        out.append("")

        n_total = results.get("edge_metrics", {}).get("total_trades", 0)
        surplus_t2 = n_total - eqg["trades_needed_t2"]
        if surplus_t2 > 0:
            out.append(f"> Trade surplus vs t=2.0 threshold: **+{surplus_t2:.0f}** (sufficient data)\n")
        else:
            out.append(f"> Trade deficit vs t=2.0 threshold: **{surplus_t2:.0f}** (need more trades)\n")

        # Gate table
        out.append("### Quality Gate Results\n")
        out.append("| # | Gate | Value | Threshold (HARD FAIL / WARN) | Verdict |")
        out.append("|---|------|-------|------------------------------|---------|")

        thresholds = [
            "Negative / < 30%",
            "> 70% / > 50%",
            "> 40% / > 30%",
            "< 1.0 / < 1.2",
            "< 100 / < 200",
            "< 1.0 / < 1.1",
        ]
        for i, g in enumerate(eqg["gates"]):
            icon = {"OK": "OK", "WARN": "!!", "HARD FAIL": "XX", "N/A": "--"}[g["verdict"]]
            out.append(f"| {i+1} | {g['gate']} | {g['value']} | {thresholds[i]} | **{icon}** |")
        out.append("")

        # Overall verdict
        v = eqg["overall_verdict"]
        if v == "PASS":
            out.append(f"> **Overall: PASS** — all gates clear. Strategy eligible for promotion.\n")
        elif v == "CONDITIONAL":
            out.append(f"> **Overall: CONDITIONAL** — {eqg['warns']} warning(s). "
                       f"Requires explicit human override to promote.\n")
        else:
            out.append(f"> **Overall: REJECT** — {eqg['hard_fails']} hard fail(s). "
                       f"Do NOT promote. Edge is not robust.\n")

    return "\n".join(out)
