"""News Policy section markdown builders (computation lives in report_news_policy)."""

from __future__ import annotations

from tools.news_calendar import derive_currencies, load_news_calendar

from tools.report.report_news_policy import (
    _NEWS_MIN_TRADES,
    _classify_all_trades_news,
    _compute_news_metrics,
    _news_compute_go_flat,
    _news_pf,
    _news_prepare_df,
)


def _news_build_portfolio_impact(baseline, no_entry, go_flat):
    """Table 1: Policy-level impact comparison."""
    md = []
    md.append("### Portfolio Impact\n")
    md.append("| Policy | Trades | Net PnL | PF | Win % | Max DD |")
    md.append("|--------|--------|---------|-----|-------|--------|")

    for label, m in [("Baseline", baseline),
                     ("No-Entry", no_entry),
                     ("Go-Flat", go_flat)]:
        pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "∞"
        if label != "Baseline" and m['trades'] < _NEWS_MIN_TRADES:
            md.append(
                f"| {label} | {m['trades']} | — | — | — | — |"
            )
        else:
            md.append(
                f"| {label} | {m['trades']} | ${m['net_pnl']:,.2f} "
                f"| {pf_s} | {m['win_pct']:.1f}% | ${m['max_dd']:,.2f} |"
            )
    md.append("")
    return md


def _news_build_per_symbol_sensitivity(df, symbols):
    """Table 2: Per-symbol news sensitivity."""
    md = []
    if not symbols:
        return md
    md.append("### Per-Symbol News Sensitivity\n")
    md.append(
        "| Symbol | Trades (News) | PF (News) | PF (Outside) | Impact |"
    )
    md.append(
        "|--------|--------------|-----------|--------------|--------|"
    )
    for sym in symbols:
        sym_df = df[df['symbol'] == sym]
        news_sub = sym_df[sym_df['_news_flag']]
        outside_sub = sym_df[~sym_df['_news_flag']]
        n_news = len(news_sub)

        if n_news == 0:
            md.append(f"| {sym} | 0 | — | — | — |")
            continue

        pf_n = _news_pf(news_sub['pnl_usd'])
        pf_o = _news_pf(outside_sub['pnl_usd']) if len(outside_sub) > 0 else 0.0

        if abs(pf_n - pf_o) < 0.1:
            impact = "Neutral"
        elif pf_n < pf_o:
            impact = "Hurts"
        else:
            impact = "Helps"

        pf_n_s = f"{pf_n:.2f}" if pf_n != float('inf') else "∞"
        pf_o_s = f"{pf_o:.2f}" if pf_o != float('inf') else "∞"
        md.append(
            f"| {sym} | {n_news} | {pf_n_s} | {pf_o_s} | {impact} |"
        )
    md.append("")
    return md


def _news_build_aggregate_table(news_agg, outside_agg):
    """Table 3: News vs Non-News aggregate performance."""
    md = []
    md.append("### News vs Non-News Performance (Aggregate)\n")
    md.append("| Segment | Trades | Net PnL | PF | Avg R |")
    md.append("|---------|--------|---------|-----|-------|")

    for label, sub in [("News Window", news_agg), ("Outside", outside_agg)]:
        cnt = len(sub)
        if cnt == 0:
            md.append(f"| {label} | 0 | — | — | — |")
            continue
        pnl = sub['pnl_usd'].sum()
        pf = _news_pf(sub['pnl_usd'])
        pf_s = f"{pf:.2f}" if pf != float('inf') else "∞"
        avg_r = (
            f"{sub['r_multiple'].mean():+.3f}"
            if 'r_multiple' in sub.columns else "N/A"
        )
        md.append(
            f"| {label} | {cnt} | ${pnl:,.2f} | {pf_s} | {avg_r} |"
        )
    md.append("")
    return md


def _news_build_interpretation(df, symbols, news_agg, outside_agg):
    """Minimal interpretation (max 2-3 lines)."""
    md = []
    if len(news_agg) == 0 or len(outside_agg) == 0:
        md.append("")
        return md
    pf_n = _news_pf(news_agg['pnl_usd'])
    pf_o = _news_pf(outside_agg['pnl_usd'])
    pf_n_s = f"{pf_n:.2f}" if pf_n != float('inf') else "∞"
    pf_o_s = f"{pf_o:.2f}" if pf_o != float('inf') else "∞"
    md.append(f"- News PF: {pf_n_s} vs Outside PF: {pf_o_s}")

    affected = []
    for sym in symbols:
        sym_df = df[df['symbol'] == sym]
        nw = sym_df[sym_df['_news_flag']]
        out = sym_df[~sym_df['_news_flag']]
        if len(nw) < 5 or len(out) < 5:
            continue
        pf_ns = _news_pf(nw['pnl_usd'])
        pf_os = _news_pf(out['pnl_usd'])
        diff = pf_ns - pf_os
        if diff > 0.1:
            affected.append(f"{sym} (helps)")
        elif diff < -0.1:
            affected.append(f"{sym} (hurts)")
    if affected:
        md.append(f"- Most affected: {', '.join(affected[:4])}")
    md.append("")
    return md


def _build_news_policy_section(all_trades_dfs, timeframe, data_root, calendar_dir):
    """Build the News Policy Impact markdown section.

    Computes Baseline / No-Entry / Go-Flat scenarios from existing trade
    logs cross-referenced against real economic calendar data.

    Returns a list of markdown lines to extend into the report body.
    """
    md = []

    # --- Load calendar ---
    cal = load_news_calendar(calendar_dir)
    if cal is None:
        md.append("---\n")
        md.append("## News Policy Impact\n")
        md.append(f"> News calendar not found at `{calendar_dir}` — section skipped.\n")
        return md

    windows_df, windows_by_currency = cal

    # --- Validate + prepare trade data ---
    df = _news_prepare_df(all_trades_dfs)
    if df is None:
        return md

    # --- Classify trades ---
    sym_ccys = {
        str(s): derive_currencies(str(s))
        for s in df['symbol'].dropna().unique()
    }

    nf, eiw, strad, ews = _classify_all_trades_news(
        df, windows_by_currency, sym_ccys
    )
    df['_news_flag'] = nf
    df['_entry_in_window'] = eiw
    df['_straddles'] = strad
    df['_earliest_ws'] = ews

    # --- Baseline ---
    baseline = _compute_news_metrics(df)

    # --- No-Entry: drop trades whose entry falls inside any window ---
    df_no_entry = df[~df['_entry_in_window']].copy()
    no_entry = _compute_news_metrics(df_no_entry)

    # --- Go-Flat: exit straddlers at earliest window_start ---
    go_flat = _news_compute_go_flat(df, timeframe, data_root)

    # ===================== Build markdown =====================
    md.append("---\n")
    md.append("## News Policy Impact\n")

    # --- 1. Portfolio Impact table ---
    md.extend(_news_build_portfolio_impact(baseline, no_entry, go_flat))

    # --- 2. Per-Symbol News Sensitivity ---
    symbols = sorted(df['symbol'].dropna().unique(), key=str)
    md.extend(_news_build_per_symbol_sensitivity(df, symbols))

    # --- 3. News vs Non-News Performance (Aggregate) ---
    news_agg = df[df['_news_flag']]
    outside_agg = df[~df['_news_flag']]
    md.extend(_news_build_aggregate_table(news_agg, outside_agg))

    # --- 4. Minimal interpretation (max 2-3 lines) ---
    md.extend(_news_build_interpretation(df, symbols, news_agg, outside_agg))

    # --- 5. Required note ---
    md.append(
        "> Note: Go-Flat assumes no entries during news windows; "
        "trades entering within windows are excluded.\n"
    )

    return md
