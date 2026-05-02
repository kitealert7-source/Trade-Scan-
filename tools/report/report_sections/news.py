"""News Policy section markdown builders (computation lives in report_news_policy)."""

from __future__ import annotations

from tools.news_calendar import derive_currencies, load_news_calendar

from tools.report.report_news_policy import (
    _NEWS_MIN_TRADES,
    _build_impact_slice_windows,
    _classify_all_trades_news,
    _classify_all_trades_news_extended,
    _compute_news_metrics,
    _compute_news_robustness,
    _compute_news_yearwise,
    _news_compute_go_flat,
    _news_pf,
    _news_prepare_df,
)


# ---------------------------------------------------------------------------
# Tier 1 — legacy tables (kept byte-stable for existing report contract)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tier 2 — extended research tables (gated; off by default for byte-stability)
# ---------------------------------------------------------------------------

def _fmt_pf(pf):
    if pf == float('inf'):
        return "∞"
    return f"{pf:.2f}"


def _news_build_pre_post_split(df):
    """Table: trade counts and PF split by pre / post / overlap relative to event_dt."""
    md = []
    md.append("### News Pre vs Post-Event Split\n")
    md.append("| Bucket | Trades | Net PnL | PF | Avg R |")
    md.append("|--------|--------|---------|-----|-------|")

    buckets = [
        ("Pre-event only", df[df['_news_pre_only']]),
        ("Post-event only", df[df['_news_post_only']]),
        ("Overlap (straddles event)", df[df['_news_overlap']]),
        ("Outside (no news)", df[~df['_news_flag']]),
    ]
    for label, sub in buckets:
        cnt = len(sub)
        if cnt == 0:
            md.append(f"| {label} | 0 | — | — | — |")
            continue
        pnl = float(sub['pnl_usd'].sum())
        pf = _news_pf(sub['pnl_usd'])
        avg_r = (
            f"{sub['r_multiple'].mean():+.3f}"
            if 'r_multiple' in sub.columns else "N/A"
        )
        md.append(
            f"| {label} | {cnt} | ${pnl:,.2f} | {_fmt_pf(pf)} | {avg_r} |"
        )
    md.append("")
    return md


def _news_build_per_impact_table(df):
    """Table: per-impact (High / Medium / Low) PF / trades / net_pnl / expectancy.

    Trades are bucketed by their *matched_impact* tag — multi-impact trades are
    grouped under the union label they actually matched (e.g. 'High,Medium').
    """
    md = []
    md.append("### Per-Impact Breakdown\n")
    md.append("| Impact Tag | Trades | Net PnL | PF | Expectancy |")
    md.append("|------------|--------|---------|-----|------------|")

    sub = df[df['_news_flag']].copy()
    if len(sub) == 0:
        md.append("| (no news trades) | 0 | — | — | — |")
        md.append("")
        return md

    # Group by raw matched_impact string so multi-impact rows are visible.
    for label, group in sub.groupby('_matched_impact', sort=True):
        if not label:
            label_disp = "(unlabeled)"
        else:
            label_disp = label
        cnt = len(group)
        pnl = float(group['pnl_usd'].sum())
        pf = _news_pf(group['pnl_usd'])
        exp = pnl / cnt
        md.append(
            f"| {label_disp} | {cnt} | ${pnl:,.2f} | {_fmt_pf(pf)} | ${exp:,.2f} |"
        )
    md.append("")
    return md


def _news_build_per_currency_table(df):
    """Table: per-currency (USD / EUR / JPY / ...) PF / trades / net_pnl / expectancy.

    Bucketed by *matched_currencies* tag from the extended classifier.
    """
    md = []
    md.append("### Per-Currency Breakdown\n")
    md.append("| Currency Tag | Trades | Net PnL | PF | Expectancy |")
    md.append("|--------------|--------|---------|-----|------------|")

    sub = df[df['_news_flag']].copy()
    if len(sub) == 0:
        md.append("| (no news trades) | 0 | — | — | — |")
        md.append("")
        return md

    for label, group in sub.groupby('_matched_currencies', sort=True):
        label_disp = label or "(unlabeled)"
        cnt = len(group)
        pnl = float(group['pnl_usd'].sum())
        pf = _news_pf(group['pnl_usd'])
        exp = pnl / cnt
        md.append(
            f"| {label_disp} | {cnt} | ${pnl:,.2f} | {_fmt_pf(pf)} | ${exp:,.2f} |"
        )
    md.append("")
    return md


def _news_build_robustness_block(df):
    """News-subset robustness metrics mirroring the main quality gate."""
    md = []
    md.append("### News-Subset Robustness Metrics\n")

    news_sub = df[df['_news_flag']]
    metrics = _compute_news_robustness(news_sub)

    md.append("| Metric | News Subset |")
    md.append("|--------|-------------|")
    md.append(f"| Trades | {metrics['trades']} |")
    md.append(f"| Net PnL | ${metrics['net_pnl']:,.2f} |")
    md.append(f"| PF | {_fmt_pf(metrics['pf'])} |")
    md.append(f"| Top-5 Concentration | {metrics['top5_pct']:.1f}% of news Net PnL |")
    md.append(f"| PF after top-5% wins removed | {_fmt_pf(metrics['pf_ex_top5pct'])} |")
    md.append(f"| Longest Flat Period (news subset) | {metrics['longest_flat_days']} days |")
    md.append(f"| Edge Ratio (news, MFE/MAE) | {metrics['edge_ratio']:.2f} |")
    md.append("")

    yw = _compute_news_yearwise(news_sub)
    if yw:
        md.append("**News-Subset Yearwise**\n")
        md.append("| Year | Trades | Net PnL | PF |")
        md.append("|------|--------|---------|-----|")
        for row in yw:
            md.append(
                f"| {row['year']} | {row['trades']} | ${row['net_pnl']:,.2f} "
                f"| {_fmt_pf(row['pf'])} |"
            )
        md.append("")
    return md


def _news_build_impact_sweep_block(df_by_slice):
    """Compare aggregate news PF across multiple impact slices side-by-side.

    df_by_slice: dict {slice_label: classified_df_for_that_slice}
    """
    md = []
    md.append("### Impact Sweep — News vs Outside by Filter\n")
    md.append("| Impact Filter | News Trades | News PF | Outside Trades | Outside PF |")
    md.append("|---------------|-------------|---------|----------------|------------|")
    for label, df_slice in df_by_slice.items():
        news_sub = df_slice[df_slice['_news_flag']]
        out_sub = df_slice[~df_slice['_news_flag']]
        pf_n = _news_pf(news_sub['pnl_usd']) if len(news_sub) else 0.0
        pf_o = _news_pf(out_sub['pnl_usd']) if len(out_sub) else 0.0
        md.append(
            f"| {label} | {len(news_sub)} | {_fmt_pf(pf_n)} "
            f"| {len(out_sub)} | {_fmt_pf(pf_o)} |"
        )
    md.append("")
    return md


# ---------------------------------------------------------------------------
# Section orchestrator
# ---------------------------------------------------------------------------

# Loader defaults — kept in sync with tools.news_calendar.load_news_calendar.
# Callers that override these will get explicit threading; callers that omit
# them get byte-identical behavior to the pre-extension report contract.
_DEFAULT_PRE_MIN = 15
_DEFAULT_POST_MIN = 15
_DEFAULT_IMPACT_FILTER = "High"


def _build_news_policy_section(
    all_trades_dfs,
    timeframe,
    data_root,
    calendar_dir,
    *,
    pre_window_minutes: int = _DEFAULT_PRE_MIN,
    post_window_minutes: int = _DEFAULT_POST_MIN,
    impact_filter: str = _DEFAULT_IMPACT_FILTER,
    impact_sweep: list | None = None,
    extended_metrics: bool = False,
):
    """Build the News Policy Impact markdown section.

    Tier-1 (default kwargs) emits the legacy 5-section contract used across
    all existing reports — kept byte-stable.

    Tier-2 (`extended_metrics=True` and/or `impact_sweep` passed) emits
    additional research tables: pre/post split, per-impact, per-currency,
    news-subset robustness, and impact-sweep comparisons.

    Parameters
    ----------
    pre_window_minutes, post_window_minutes : int
        Asymmetric pre/post window size around each event_dt. Threaded into
        load_news_calendar() — explicit even when equal to defaults so the
        report no longer depends on loader-default coupling.
    impact_filter : str or None
        Single-impact filter for the primary classification ("High",
        "Medium", "Low"). Pass None or "All" to disable filtering.
    impact_sweep : list[str] or None
        If given (e.g. ["High", "High+Medium", "Medium"]), emits an
        additional Impact Sweep table comparing news/outside PF across
        each slice. Each slice may use "+"-union notation. Trade-level
        classification is computed once against the full event set and
        post-filtered per slice.
    extended_metrics : bool
        When True, emit pre/post split, per-impact, per-currency, and
        news-subset robustness tables in addition to the legacy contract.
    """
    md = []

    # --- Load primary calendar (single-impact for legacy tables) ---
    cal = load_news_calendar(
        calendar_dir,
        pre_min=pre_window_minutes,
        post_min=post_window_minutes,
        impact_filter=impact_filter,
    )
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

    # --- Classify trades (extended classifier — emits all tags) ---
    sym_ccys = {
        str(s): derive_currencies(str(s))
        for s in df['symbol'].dropna().unique()
    }

    tags = _classify_all_trades_news_extended(
        df, windows_by_currency, sym_ccys
    )
    df['_news_flag'] = tags['news_flag']
    df['_entry_in_window'] = tags['entry_in_window']
    df['_straddles'] = tags['straddles']
    df['_earliest_ws'] = tags['earliest_ws']
    df['_news_pre_only'] = tags['news_pre_only']
    df['_news_post_only'] = tags['news_post_only']
    df['_news_overlap'] = tags['news_overlap']
    df['_matched_impact'] = tags['matched_impact']
    df['_matched_currencies'] = tags['matched_currencies']
    df['_match_count'] = tags['match_count']

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

    # ----- Tier-2 (gated, additive) -----------------------------------
    if extended_metrics:
        md.append("---\n")
        md.append("### Extended News Research\n")
        md.append(
            f"_Pre-window: {pre_window_minutes}min · "
            f"Post-window: {post_window_minutes}min · "
            f"Impact filter: {impact_filter}_\n"
        )
        md.extend(_news_build_pre_post_split(df))
        md.extend(_news_build_per_impact_table(df))
        md.extend(_news_build_per_currency_table(df))
        md.extend(_news_build_robustness_block(df))

    if impact_sweep:
        md.extend(
            _build_impact_sweep_section(
                all_trades_dfs, calendar_dir,
                pre_window_minutes, post_window_minutes,
                impact_sweep, sym_ccys,
            )
        )

    return md


def _build_impact_sweep_section(
    all_trades_dfs,
    calendar_dir,
    pre_min,
    post_min,
    impact_sweep,
    sym_ccys,
):
    """Run the classifier once per impact slice and emit a comparison table.

    Loads the calendar with impact_filter=None (full event set) once, then
    slices windows in-memory per requested label. No loader / cache changes.
    """
    md = []
    cal = load_news_calendar(
        calendar_dir,
        pre_min=pre_min, post_min=post_min,
        impact_filter=None,
    )
    if cal is None:
        return md
    windows_df_all, _ = cal

    df_by_slice: dict = {}
    for label in impact_sweep:
        sliced_wdf, sliced_by_ccy = _build_impact_slice_windows(
            windows_df_all, label
        )
        if sliced_wdf is None or len(sliced_wdf) == 0:
            continue
        df_slice = _news_prepare_df(all_trades_dfs)
        if df_slice is None:
            continue
        tags = _classify_all_trades_news_extended(
            df_slice, sliced_by_ccy, sym_ccys
        )
        df_slice['_news_flag'] = tags['news_flag']
        df_by_slice[label] = df_slice

    if df_by_slice:
        md.extend(_news_build_impact_sweep_block(df_by_slice))
    return md
