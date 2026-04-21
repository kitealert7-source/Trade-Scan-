"""Backtest markdown-report orchestration (Stage-5).

Thin CLI + orchestrator — all section builders, data collectors, insights,
news-policy logic, and file writing live under tools/report/.
Re-exports the prior public+test surface so back-compat imports keep working.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tools.pipeline_utils import get_engine_version

# --- Back-compat re-exports (used by tests/test_news_policy.py,
#     tools/run_stage1.py, tools/orchestration/stage_portfolio.py,
#     and any ad-hoc scripts that reach into these helpers) --------------
from tools.report.report_sessions import (  # noqa: F401
    _ASIA_START, _ASIA_END, _LONDON_START, _LONDON_END, _NY_START, _NY_END,
    _OVERLAP_START, _OVERLAP_END, _LATE_NY_START, _LATE_NY_END,
    _WEEKDAY_NAMES,
    _build_cross_tab,
    _classify_session,
    _classify_weekday,
    _conf_tag,
    _is_late_ny,
    _is_overlap,
)
from tools.report.report_insights import (  # noqa: F401
    _derive_insights,
    _build_insights_section,
    _insight_direction_asymmetry,
    _insight_direction_volatility_trend,
    _insight_exit_structure,
    _insight_late_ny_asymmetry,
    _insight_mfe_giveback,
    _insight_regime_age_gradient,
    _insight_session_divergence,
    _insight_trade_density,
)
from tools.report.report_news_policy import (  # noqa: F401
    _NEWS_MIN_TRADES,
    _classify_all_trades_news,
    _compute_news_metrics,
    _get_price_at,
    _load_ohlc_for_symbol,
    _news_compute_go_flat,
    _news_pf,
    _news_prepare_df,
)
from tools.report.report_collector import (  # noqa: F401
    SymbolPayloads,
    _collect_age_entry,
    _collect_dual_age,
    _collect_exec_delta,
    _collect_session_row,
    _collect_symbol_payloads,
    _collect_vol_trend_edges,
    _compute_portfolio_totals,
    _load_symbol_data,
)
from tools.report.report_writer import _write_markdown_reports  # noqa: F401
from tools.report.report_sections.news import (  # noqa: F401
    _build_news_policy_section,
    _news_build_aggregate_table,
    _news_build_interpretation,
    _news_build_per_symbol_sensitivity,
    _news_build_portfolio_impact,
)
from tools.report.report_sections.risk import (  # noqa: F401
    _build_edge_decomposition_section,
    _build_exit_analysis_section,
    _build_risk_characteristics_section,
)
from tools.report.report_sections.session import (  # noqa: F401
    _build_age_section,
    _build_exec_delta_section,
    _build_fill_age_section,
    _build_htf_delta_section,
    _build_session_late_ny_subsection,
    _build_session_overlap_subsection,
    _build_session_section,
    _build_weekday_section,
)
from tools.report.report_sections.summary import (  # noqa: F401
    _build_direction_split_section,
    _build_header_section,
    _build_key_metrics_section,
    _build_symbol_summary_section,
    _build_trend_edge_section,
    _build_volatility_edge_section,
    _build_yearwise_section,
)
from tools.report.report_strategy_portfolio import (  # noqa: F401
    generate_strategy_portfolio_report,
)


# ===========================================================================
# Public entrypoint — thin orchestrator
# ===========================================================================

def generate_backtest_report(directive_name: str, backtest_root: Path, *,
                             show_overlap: bool = False, show_late_ny: bool = False,
                             show_weekday: bool = False):
    """
    Generates a deterministic markdown report from raw CSV artifacts without altering state.
    Provides run-level metrics (Stage-5A).
    The generated report is saved inside each matching symbol directory within the backtest namespace.

    Args:
        show_overlap: If True, append London-NY overlap analysis (13-16 UTC) to Session Breakdown.
        show_late_ny: If True, append Late NY analysis (21-24 UTC) to Session Breakdown.
        show_weekday: If True, append weekday breakdown + Direction × Day cross-tab.
    """
    symbol_dirs = [d for d in backtest_root.iterdir()
                   if d.is_dir() and d.name.startswith(f"{directive_name}_")]

    # 1. Load per-symbol payloads (all CSV I/O happens here)
    pl = _collect_symbol_payloads(symbol_dirs, directive_name)

    # 2. Portfolio-level totals (trade-weighted averages + worst-case DD)
    totals = _compute_portfolio_totals(pl)

    # 3. Counts for header + stage-mode banner
    valid_symbol_dirs = [
        s_dir for s_dir in symbol_dirs
        if (s_dir / "raw" / "results_tradelevel.csv").exists()
    ]
    stage3_counts = sum(
        (s_dir / "raw" / "results_standard.csv").exists() and
        (s_dir / "raw" / "results_risk.csv").exists()
        for s_dir in valid_symbol_dirs
    )
    total_symbols = len(valid_symbol_dirs)

    engine_ver = get_engine_version()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 4. Build markdown section-by-section (section order is the report contract)
    md = []
    header_md, port_pf_str = _build_header_section(
        directive_name, engine_ver, pl.timeframe, pl.start_date, pl.end_date,
        total_symbols, len(symbol_dirs), now_utc, stage3_counts, totals["port_pf"],
    )
    md.extend(header_md)
    md.extend(_build_key_metrics_section(
        pl.portfolio_pnl, pl.portfolio_trades, port_pf_str, totals, pl.risk_data_list,
    ))
    md.extend(_build_direction_split_section(pl.all_trades_dfs))
    md.extend(_build_symbol_summary_section(pl.symbols_data))
    md.extend(_build_yearwise_section(pl.all_trades_dfs))
    md.extend(_build_volatility_edge_section(pl.vol_data))
    md.extend(_build_trend_edge_section(pl.trend_data))
    md.extend(_build_age_section(pl.age_data))
    md.extend(_build_fill_age_section(pl.fill_age_data))
    md.extend(_build_htf_delta_section(pl.delta_age_data, pl.dual_meta_data))
    md.extend(_build_exec_delta_section(pl.exec_delta_data, pl.exec_meta_data))
    md.extend(_build_session_section(pl.all_trades_dfs, pl.session_data, show_overlap, show_late_ny))
    md.extend(_build_weekday_section(pl.all_trades_dfs, show_weekday))
    md.extend(_build_exit_analysis_section(pl.all_trades_dfs))
    md.extend(_build_edge_decomposition_section(pl.all_trades_dfs))
    md.extend(_build_risk_characteristics_section(pl.all_trades_dfs))

    # News policy (delegates to sections.news orchestrator)
    _data_root = Path(__file__).resolve().parent.parent / "data_root"
    _calendar_dir = _data_root / "EXTERNAL_DATA" / "NEWS_CALENDAR" / "RESEARCH"
    md.extend(_build_news_policy_section(pl.all_trades_dfs, pl.timeframe, _data_root, _calendar_dir))

    md.extend(_build_insights_section(
        pl.all_trades_dfs, pl.risk_data_list, pl.portfolio_pnl, pl.portfolio_trades, totals["port_pf"],
    ))

    # 5. Write
    md_content = "\n".join(md)
    _write_markdown_reports(symbol_dirs, directive_name, md_content)

    print("\n[STAGE-1 COMPLETE]")
    print("Edge Decomposition Report Generated.")
    print("Next action required:")
    print("1) Reject")
    print("2) Create filtered variant (P01/P02)")
    print("3) Run full pipeline (Stage-2+)")
    print("Awaiting user decision...\n")
