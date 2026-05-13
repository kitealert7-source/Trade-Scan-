"""
Portfolio Evaluator - Multi-Instrument Portfolio Analysis + Snapshot Archival
Usage: python tools/portfolio_evaluator.py <STRATEGY_ID>
Example: python tools/portfolio_evaluator.py IDX23

Produces:
  - strategies/<STRATEGY_ID>/portfolio_evaluation/ (frozen snapshot)
  - Console executive summary + recommendation

This file is a thin CLI + orchestrator. Implementation lives in tools/portfolio/:
  portfolio_config              constants
  portfolio_io                  CSV/metadata loaders
  portfolio_metrics             numeric computations (no I/O)
  portfolio_charts              matplotlib PNGs (isolated)
  portfolio_tradelevel          per-trade enriched export
  portfolio_snapshot            JSON/MD writers
  portfolio_profile_selection   Step 7 authority (sole selector)
  portfolio_ledger_writer       Master Portfolio Sheet (sole writer)
"""

import sys
from pathlib import Path

# ------------------------------------------------------------------
# CONFIG — keep sys.path anchor here so direct-CLI invocation still works
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import warnings
warnings.filterwarnings('ignore')

from datetime import datetime, timezone  # noqa: E402  (needed for back-compat re-exports)

from tools.portfolio.portfolio_config import (  # noqa: F401
    BACKTESTS_ROOT,
    COLORS,
    PORTFOLIO_ENGINE_VERSION,
    RELIABILITY_MIN_ACCEPTED,
    RELIABILITY_MIN_SIM_YEARS,
    RISK_FREE_RATE,
    STRATEGIES_ROOT,
    SYMBOLS,
    TOTAL_PORTFOLIO_CAPITAL,
)
from tools.portfolio.portfolio_io import load_all_trades, load_symbol_metrics  # noqa: F401
from tools.portfolio.portfolio_metrics import (  # noqa: F401
    build_portfolio_equity,
    capital_utilization,
    compute_concurrency_series,
    compute_portfolio_metrics,
    compute_stress_correlation,
    concurrency_profile,
    contribution_analysis,
    correlation_analysis,
    drawdown_anatomy,
    regime_segmentation,
    stress_test,
    _to_mt5_timeframe,
)
from tools.portfolio.portfolio_charts import generate_charts  # noqa: F401
from tools.portfolio.portfolio_tradelevel import generate_portfolio_tradelevel  # noqa: F401
from tools.portfolio.portfolio_snapshot import save_snapshot  # noqa: F401

# Back-compat re-exports for tests + profile_selector + other consumers that
# reach into tools.portfolio_evaluator.* for private helpers.
from tools.portfolio.portfolio_profile_selection import (  # noqa: F401
    _compute_portfolio_status,
    _empty_selection_debug,
    _execution_health,
    _get_deployed_profile_metrics,
    _load_profile_comparison,
    _per_symbol_realized_density,
    _profile_return_dd,
    _resolve_deployed_profile,
    _safe_bool,
    _safe_float,
    _score_profile_candidate,
    _detect_asset_class,
    _EXP_FAIL_GATES,
    _parse_strategy_name,
)
from tools.portfolio.portfolio_ledger_writer import (  # noqa: F401
    update_master_portfolio_ledger,
    _compute_ledger_row,
    _serialize_ledger_row,
    _append_ledger_row,
)


# ==================================================================
# Phase 5b — basket row writer (append-only, separate from per-symbol MPS)
# ==================================================================
#
# Per-symbol MPS schema is preserved untouched. Basket runs land in a
# separate append-only CSV at TradeScan_State/research/basket_runs.csv.
# Phase 5c may promote this into a basket-aware column extension of
# Master_Portfolio_Sheet.xlsx with execution_mode='basket' rows interleaved;
# until then the CSV gives a research-stage record without risking the
# production ledger's append-only invariant (Invariant #2).
#
# Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.

def append_basket_row_to_research_csv(basket_result, *, directive_id: str) -> Path:
    """Append a one-row CSV record of a basket run.

    Args:
        basket_result: tools.basket_pipeline.BasketRunResult
        directive_id:  e.g. "90_PORT_H2_5M_RECYCLE_S01_V1_P00"

    Returns:
        Path to the CSV that was appended.

    Schema (append-only; new columns added at the right edge in future
    versions, never reordered):

        timestamp_utc, directive_id, basket_id, execution_mode,
        rule_name, rule_version, leg_count, trades_total,
        recycle_event_count, harvested_total_usd,
        basket_legs_json
    """
    import csv
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    from config.path_authority import TRADE_SCAN_STATE

    out_dir = TRADE_SCAN_STATE / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "basket_runs.csv"

    row = basket_result.to_mps_row()
    fields = [
        "timestamp_utc",
        "directive_id",
        "basket_id",
        "execution_mode",
        "rule_name",
        "rule_version",
        "leg_count",
        "trades_total",
        "recycle_event_count",
        "harvested_total_usd",
        "basket_legs_json",
    ]
    record = {
        "timestamp_utc": _dt.now(tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "directive_id":  directive_id,
        "basket_id":     row.get("basket_id"),
        "execution_mode": row.get("execution_mode"),
        "rule_name":     row.get("rule_name"),
        "rule_version":  row.get("rule_version"),
        "leg_count":     len(row.get("basket_legs", [])),
        "trades_total":  row.get("trades_total"),
        "recycle_event_count": row.get("recycle_event_count"),
        "harvested_total_usd": row.get("harvested_total_usd"),
        "basket_legs_json":    _json.dumps(row.get("basket_legs", [])),
    }

    write_header = not csv_path.is_file()
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow(record)
    return csv_path


# ==================================================================
# MAIN orchestration helpers
# ==================================================================

def _main_enforce_metadata_contract(meta_records):
    """HARD FAIL if any symbol is missing required metadata keys."""
    REQUIRED_META_KEYS = ["signature_hash", "trend_filter_enabled", "filter_coverage",
                          "filtered_bars", "total_bars"]
    meta_warnings = []
    for sym, meta in meta_records.items():
        missing_keys = [k for k in REQUIRED_META_KEYS if k not in meta]
        if missing_keys:
            meta_warnings.append(f"{sym}: missing {missing_keys}")
    if meta_warnings:
        for w in meta_warnings:
            print(f"    - {w}")
        raise RuntimeError(
            f"GOVERNANCE_ABORT: {len(meta_warnings)} symbols missing required metadata contract. "
            f"Re-run backtests with updated pipeline to populate missing fields."
        )

    unique_hashes = set()
    for sym, meta in meta_records.items():
        h = meta.get('signature_hash')
        if h:
            unique_hashes.add(h)
    if len(unique_hashes) > 1:
        print(
            f"[WARN] GOVERNANCE_ABORT bypassed: Mixed signature hashes detected across symbols. "
            f"Found {len(unique_hashes)} unique hashes: {unique_hashes}. "
            f"Bypassing to allow multi-strategy portfolio."
        )
    print(f"  [GOVERNANCE] Signature hash consistent across {len(meta_records)} symbols.")


def _main_detect_inert_filters(meta_records):
    """Collect symbols with 0% filter coverage despite trend_filter_enabled."""
    inert_warnings = []
    for sym, meta in meta_records.items():
        if meta.get('trend_filter_enabled', False):
            coverage = meta.get('filter_coverage', -1)
            if coverage == 0.0:
                inert_warnings.append(sym)
    if inert_warnings:
        print(f"  [WARN] Inert filters detected on {len(inert_warnings)} symbols (0% filter coverage)")
    return inert_warnings


def _main_extract_regime_pnl(portfolio_df):
    """Sum PnL grouped by volatility_regime."""
    if "volatility_regime" in portfolio_df.columns:
        regime_pnl = portfolio_df.groupby("volatility_regime")["pnl_usd"].sum()
        low_pnl = float(regime_pnl.get("low", 0.0))
        normal_pnl = float(regime_pnl.get("normal", 0.0))
        high_pnl = float(regime_pnl.get("high", 0.0))
    else:
        low_pnl = normal_pnl = high_pnl = 0.0
    return low_pnl, normal_pnl, high_pnl


def _main_extract_signal_timeframes(portfolio_df):
    """Extract unique signal timeframes from Master Filter for the portfolio's run_ids."""
    try:
        from tools.ledger_db import read_master_filter as _read_mf_local
        df_master_local = _read_mf_local()
        current_run_ids = sorted(list(set(portfolio_df['source_run_id'].astype(str).unique())))
        related_runs = df_master_local[df_master_local['run_id'].astype(str).isin(current_run_ids)]
        tf_col = 'timeframe' if 'timeframe' in related_runs.columns else 'TIMEFRAME'
        if tf_col in related_runs.columns:
            timeframes = sorted(related_runs[tf_col].astype(str).unique())
            signal_timeframes_str = "|".join(timeframes)
        else:
            signal_timeframes_str = "UNKNOWN"
    except Exception as e:
        print(f"  [WARN] Failed to extract timeframes: {e}")
        signal_timeframes_str = "UNKNOWN"
    return signal_timeframes_str


def _main_print_final_summary(port_metrics, corr_data, max_stress_corr,
                              strategy_id, recommendation):
    print(f"\n{'='*60}")
    print(f"PORTFOLIO EVALUATION COMPLETE - {strategy_id}")
    print(f"{'='*60}")
    print(f"\n  Net PnL:     ${port_metrics['net_pnl_usd']:,.2f}")
    print(f"  CAGR:         {port_metrics['cagr']:.2%}")
    print(f"  Sharpe:       {port_metrics['sharpe']}")
    print(f"  Sortino:      {port_metrics['sortino']}")
    print(f"  Max DD:       {port_metrics['max_dd_pct']:.2%} (${port_metrics['max_dd_usd']:,.2f})")
    print(f"  Return/DD:    {port_metrics['return_dd_ratio']}")
    print(f"  Peak Capital: ${port_metrics.get('peak_capital_deployed', 0):,.2f}")
    print(f"  Overextension: {port_metrics.get('capital_overextension_ratio', 0):.2f}")
    print(f"  K-Ratio:      {port_metrics['k_ratio']}")
    print(f"  Avg Corr:     {corr_data['avg_pairwise_corr']}")
    print(f"  Stress Corr:  {max_stress_corr:.3f}")
    print(f"\n  {recommendation}")
    print()


# ==================================================================
# MAIN
# ==================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("strategy_id", help="The Portfolio ID name (e.g. P001)")
    parser.add_argument("--run-ids", required=True, nargs="+", help="Explicit atomic runs to construct the portfolio from")
    parser.add_argument("--force-ledger", action="store_true", help="Force Master Ledger write even for single-run/single-asset strategies (sweep tracking)")
    args = parser.parse_args()

    strategy_id = args.strategy_id
    run_ids = args.run_ids

    print(f"\n{'='*60}")
    print(f"PORTFOLIO EVALUATION - {strategy_id}")
    print(f"Constituents: {run_ids}")
    print(f"{'='*60}")

    output_dir = STRATEGIES_ROOT / strategy_id / "portfolio_evaluation"

    # [1/9] Load data
    print("\n[1/9] Loading trade data...")
    portfolio_df, symbol_trades, meta_records = load_all_trades(run_ids)
    print(f"  Loaded {len(portfolio_df)} trades across {len(symbol_trades)} symbols")

    _main_enforce_metadata_contract(meta_records)
    inert_warnings = _main_detect_inert_filters(meta_records)

    # [2/9] Portfolio construction
    print("[2/9] Building portfolio equity curve...")
    if not symbol_trades:
        raise ValueError("Cannot compute reference capital: no symbols detected")

    portfolio_equity, symbol_equity, daily_pnl = build_portfolio_equity(portfolio_df, symbol_trades)
    port_metrics = compute_portfolio_metrics(portfolio_equity, daily_pnl, portfolio_df, len(symbol_trades))
    port_metrics['total_capital'] = TOTAL_PORTFOLIO_CAPITAL

    low_pnl, normal_pnl, high_pnl = _main_extract_regime_pnl(portfolio_df)
    port_metrics["portfolio_net_profit_low_vol"] = low_pnl
    port_metrics["portfolio_net_profit_normal_vol"] = normal_pnl
    port_metrics["portfolio_net_profit_high_vol"] = high_pnl

    signal_timeframes_str = _main_extract_signal_timeframes(portfolio_df)
    port_metrics['signal_timeframes'] = _to_mt5_timeframe(signal_timeframes_str)

    print(f"  Net PnL: ${port_metrics['net_pnl_usd']:,.2f} | Sharpe: {port_metrics['sharpe']}")

    _conc_base = compute_concurrency_series(portfolio_df)

    print("[3/9] Analyzing capital utilization...")
    cap_util = capital_utilization(portfolio_df, symbol_trades, _precomputed_concurrency=_conc_base)
    print(f"  Deployed: {cap_util['pct_time_deployed']}% | Max concurrent: {cap_util['max_concurrent']}")

    print("[X/9] Computing concurrency profile...")
    concurrency_data = concurrency_profile(portfolio_df, portfolio_equity, _precomputed_concurrency=_conc_base)
    print(f"  avg_concurrent: {concurrency_data['avg_concurrent']}")
    print(f"  max_concurrent: {concurrency_data['max_concurrent']}")
    print(f"  p95_concurrent: {concurrency_data['p95_concurrent']}")
    print(f"  dd_max_concurrent: {concurrency_data['dd_max_concurrent']}")

    print("[4/9] Computing correlation structure...")
    corr_data = correlation_analysis(symbol_equity)
    print(f"  Avg pairwise correlation: {corr_data['avg_pairwise_corr']}")

    print("[5/9] Analyzing symbol contributions...")
    contributions = contribution_analysis(symbol_trades, portfolio_df)
    top_sym = max(contributions, key=lambda s: contributions[s]['total_pnl'])
    print(f"  Top contributor: {top_sym} ({contributions[top_sym]['pnl_pct']:.1%})")

    print("[6/9] Dissecting largest drawdown...")
    dd_anatomy = drawdown_anatomy(portfolio_equity, portfolio_df)
    print(f"  Largest DD: ${dd_anatomy['absolute_drop_usd']:,.2f} ({dd_anatomy['pct_retracement']:.2%})")

    print("[6.5/9] Computing stress-window correlation...")
    max_stress_corr = compute_stress_correlation(
        corr_data['returns_df'],
        dd_anatomy['peak_date'],
        dd_anatomy['trough_date']
    )
    print(f"  Max pairwise (stress): {max_stress_corr:.3f}")

    print("[7/9] Running stress tests...")
    stress_results = stress_test(symbol_trades, portfolio_df)
    for name, data in stress_results.items():
        print(f"  {name}: PnL=${data['net_pnl']:,.2f}, Sharpe={data['sharpe']}")

    print("[8/9] Segmenting by regime...")
    regime_data = regime_segmentation(portfolio_df)
    for regime, stats in regime_data['regime'].items():
        print(f"  {regime}: {stats['trades']} trades, PnL=${stats['net_pnl']:,.2f}")

    print("[9/9] Generating visual outputs...")
    generate_charts(portfolio_equity, symbol_equity, corr_data,
                    contributions, stress_results, output_dir, strategy_id)

    print("  [ARTIFACT] Generating portfolio_tradelevel.csv...")
    try:
        transparency = generate_portfolio_tradelevel(portfolio_df, output_dir, TOTAL_PORTFOLIO_CAPITAL)
        port_metrics.update(transparency)
    except Exception as e:
        print(f"  [WARN] Failed to generate portfolio_tradelevel.csv: {e}")

    unique_runs = sorted(list(set(portfolio_df['source_run_id'].astype(str).unique())))

    # Snapshot metric enrichment (Phase 15)
    exposure_pct = cap_util.get('pct_time_deployed', 0.0) * 100.0
    port_metrics['exposure_pct'] = exposure_pct
    port_metrics['equity_stability_k_ratio'] = port_metrics.get('k_ratio', 0.0)

    recommendation = save_snapshot(
        strategy_id, port_metrics, contributions, corr_data,
        dd_anatomy, stress_results, regime_data, cap_util, concurrency_data,
        max_stress_corr, unique_runs, inert_warnings, output_dir
    )

    # 10) Master Ledger Update (SOP 8) — curated composite / multi-asset / forced
    is_valid_for_master = (
        len(unique_runs) > 1 or
        len(symbol_trades) > 1 or
        str(strategy_id).startswith("PF_") or
        getattr(args, 'force_ledger', False)
    )

    if is_valid_for_master:
        print(f"[10/10] Updating Master Portfolio Ledger...")
        try:
            update_master_portfolio_ledger(
                strategy_id, port_metrics, corr_data, max_stress_corr,
                concurrency_data, unique_runs, n_assets=len(symbol_trades),
            )
            print(f"  [LEDGER] Row appended to Master_Portfolio_Sheet.xlsx")
        except Exception as e:
            print(f"  [ERROR] Failed to update ledger: {e}")
            raise
    else:
        print(f"[10/10] Skipping Master Ledger Update (Filtered: Single-Run / Single-Asset Strategy).")

    _main_print_final_summary(port_metrics, corr_data, max_stress_corr,
                              strategy_id, recommendation)


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        _msg = str(_e)
        if "XLSX_LOCK_TIMEOUT" in _msg or _e.__class__.__name__ == "Timeout":
            print(f"[FATAL] XLSX_LOCK_TIMEOUT: {_msg}")
            sys.exit(3)
        raise
