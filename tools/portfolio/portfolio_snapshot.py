"""Frozen per-strategy snapshot writers (JSON + Markdown + CSV)."""

from __future__ import annotations

import csv
import json
from datetime import datetime

from tools.portfolio.portfolio_config import PORTFOLIO_ENGINE_VERSION, TOTAL_PORTFOLIO_CAPITAL


def _snapshot_write_summary_json(strategy_id, port_metrics, contributions, corr_data,
                                 concurrency_data, max_stress_corr, constituent_run_ids,
                                 inert_warnings, output_dir):
    """Write portfolio_summary.json, return the summary dict."""
    summary = {
        'strategy_id': strategy_id,
        'evaluation_date': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'portfolio_engine_version': PORTFOLIO_ENGINE_VERSION,
        'data_range': f"{port_metrics['start_date']} to {port_metrics['end_date']}",
        'total_constituent_runs': len(constituent_run_ids) if isinstance(constituent_run_ids, list) else 1,
        'total_assets_evaluated': len(contributions),
        'capital_per_symbol': TOTAL_PORTFOLIO_CAPITAL / len(contributions),
        'total_capital': TOTAL_PORTFOLIO_CAPITAL,
        'net_pnl_usd': port_metrics['net_pnl_usd'],
        'cagr_pct': port_metrics['cagr'],
        'sharpe': port_metrics['sharpe'],
        'sortino': port_metrics['sortino'],
        'max_dd_usd': port_metrics['max_dd_usd'],
        'max_dd_pct': port_metrics['max_dd_pct'],
        'return_dd_ratio': port_metrics['return_dd_ratio'],
        'k_ratio': port_metrics['k_ratio'],
        'mar': port_metrics['mar'],
        'avg_correlation': corr_data['avg_pairwise_corr'],
        'max_pairwise_corr_stress': max_stress_corr,
        'avg_concurrent': concurrency_data['avg_concurrent'],
        'max_concurrent': concurrency_data['max_concurrent'],
        'p95_concurrent': concurrency_data['p95_concurrent'],
        'dd_max_concurrent': concurrency_data['dd_max_concurrent'],
        'full_load_cluster': concurrency_data['full_load_cluster'],
        'pct_days_at_max': concurrency_data['pct_days_at_max'],
        'top_contributor_pct': max(c['pnl_pct'] for c in contributions.values()),
        'total_trades': port_metrics['total_trades'],
        'peak_capital_deployed': port_metrics.get('peak_capital_deployed', 0.0),
        'capital_overextension_ratio': port_metrics.get('capital_overextension_ratio', 0.0),
        'portfolio_net_profit_low_vol': port_metrics.get('portfolio_net_profit_low_vol', 0.0),
        'portfolio_net_profit_normal_vol': port_metrics.get('portfolio_net_profit_normal_vol', 0.0),
        'portfolio_net_profit_high_vol': port_metrics.get('portfolio_net_profit_high_vol', 0.0),
        'signal_timeframes': port_metrics.get('signal_timeframes', "UNKNOWN"),
        'win_rate': port_metrics.get('win_rate', 0.0),
        'profit_factor': port_metrics.get('profit_factor', 0.0),
        'expectancy': port_metrics.get('expectancy', 0.0),
        'exposure_pct': port_metrics.get('exposure_pct', 0.0),
        'equity_stability_k_ratio': port_metrics.get('equity_stability_k_ratio', 0.0),
        'inert_filter_warnings': inert_warnings
    }
    with open(output_dir / 'portfolio_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=4)
    return summary


def _snapshot_write_metadata_json(strategy_id, contributions, constituent_run_ids,
                                   summary, port_metrics, output_dir):
    """Write portfolio_metadata.json."""
    metadata = {
      "portfolio_id": strategy_id,
      "creation_timestamp_utc": datetime.utcnow().isoformat(),
      "constituent_run_ids": constituent_run_ids,
      "evaluated_assets": list(contributions.keys()),
      "total_constituent_runs": len(constituent_run_ids) if isinstance(constituent_run_ids, list) else 1,
      "total_assets_evaluated": len(contributions),
      "reference_capital_usd": summary['total_capital'],
      "capital_model_version": "v1.0_trade_close_compounding",
      "portfolio_engine_version": PORTFOLIO_ENGINE_VERSION,
      "schema_version": "1.0",
      "signal_timeframes": port_metrics.get('signal_timeframes', "UNKNOWN")
    }
    with open(output_dir / 'portfolio_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=4)


def _snapshot_write_metrics_csv(port_metrics, output_dir):
    """Write portfolio_metrics.csv."""
    with open(output_dir / 'portfolio_metrics.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value'])
        for k, v in port_metrics.items():
            w.writerow([k, v])


def _snapshot_recommendation(port_metrics, corr_data, contributions, concurrency_data):
    """Compute recommendation score + banner text."""
    score = 0
    if port_metrics['sharpe'] >= 1.0: score += 2
    elif port_metrics['sharpe'] >= 0.5: score += 1
    if port_metrics['return_dd_ratio'] >= 2.0: score += 2
    elif port_metrics['return_dd_ratio'] >= 1.0: score += 1
    if abs(port_metrics['max_dd_pct']) <= 0.10: score += 1
    if port_metrics['net_pnl_usd'] > 0: score += 1
    if corr_data['avg_pairwise_corr'] < 0.5: score += 1
    top_conc = max(c['pnl_pct'] for c in contributions.values())
    if top_conc < 0.30: score += 1
    if concurrency_data['p95_concurrent'] <= 4: score += 1

    if score >= 7:
        recommendation = "**PROMOTE** - Strong structural edge, diversified, robust under stress."
    elif score >= 4:
        recommendation = "**HOLD** - Positive edge but concentration or fragility concerns require further testing."
    else:
        recommendation = "**REJECT** - Insufficient edge, structural weakness, or excessive concentration."
    return recommendation, top_conc


def _snapshot_build_overview_md(strategy_id, port_metrics, contributions, corr_data,
                                 dd_anatomy, stress_results, regime_data, cap_util,
                                 concurrency_data, inert_warnings, recommendation, top_conc):
    """Build portfolio_overview.md content."""
    top_sym = max(contributions, key=lambda s: contributions[s]['total_pnl'])
    worst_sym = min(contributions, key=lambda s: contributions[s]['total_pnl'])

    baseline_pnl = stress_results.get('baseline', {}).get('net_pnl', 0)
    us_removed = [v for k, v in stress_results.items() if 'US_cluster' in k]
    us_removed_pnl = us_removed[0]['net_pnl'] if us_removed else 0
    us_dependency = ((baseline_pnl - us_removed_pnl) / baseline_pnl) if baseline_pnl != 0 else 0.0

    overview = f"""# {strategy_id} - Portfolio Evaluation Summary

## Portfolio Key Metrics (All Symbols Combined)

| Metric | Value |
|--------|-------|
| Net PnL | ${port_metrics['net_pnl_usd']:,.2f} |
| CAGR | {port_metrics['cagr']:.2%} |
| Sharpe | {port_metrics['sharpe']:.2f} |
| Sortino | {port_metrics['sortino']:.2f} |
| Max DD (USD) | ${port_metrics['max_dd_usd']:,.2f} |
| Max DD (%) | {port_metrics['max_dd_pct']:.2%} |
| Return/DD | {port_metrics['return_dd_ratio']:.2f} |
| K-Ratio | {port_metrics['k_ratio']:.2f} |
| MAR | {port_metrics['mar']:.2f} |
| Avg Correlation | {corr_data['avg_pairwise_corr']:.3f} |
| Total Trades | {port_metrics['total_trades']} |
| Period | {port_metrics['start_date']} to {port_metrics['end_date']} ({port_metrics['years']:.1f} yrs) |

## Top/Worst Contributors

- **Top**: {top_sym} (${contributions[top_sym]['total_pnl']:,.2f}, {contributions[top_sym]['pnl_pct']:.1%})
- **Worst**: {worst_sym} (${contributions[worst_sym]['total_pnl']:,.2f}, {contributions[worst_sym]['pnl_pct']:.1%})

## Capital Utilization

- Time deployed: {cap_util['pct_time_deployed']:.1%}
- Avg concurrent positions: {cap_util['avg_concurrent']:.2f}
- Max concurrent: {cap_util['max_concurrent']}

## Concurrency Profile

- 95th percentile concurrency: {concurrency_data['p95_concurrent']:.2f}
- Pct days at max concurrency: {concurrency_data['pct_days_at_max']:.1%}
- Avg concurrency during largest DD: {concurrency_data['dd_avg_concurrent']:.2f}
- Max concurrency during largest DD: {concurrency_data['dd_max_concurrent']}
- Regime avg concurrency:
    - Low: {concurrency_data['regime_avg'].get('low', 0.0):.2f}
    - Normal: {concurrency_data['regime_avg'].get('normal', 0.0):.2f}
    - High: {concurrency_data['regime_avg'].get('high', 0.0):.2f}
"""

    if concurrency_data['full_load_cluster']:
        overview += """
[WARN] **Full-load clustering detected**: 95th percentile concurrency equals maximum concurrency. Monitor regime transition risk.
"""
    if inert_warnings:
        overview += f"""
[WARN] **INERT FILTER WARNING**: The following symbols have filters enabled but 0% coverage (0 bars filtered during execution), indicating the filter had no effect vs un-filtered baseline: {', '.join(inert_warnings)}
"""

    overview += f"""
## Risk Assessment

- Largest drawdown: {dd_anatomy['peak_date']} to {dd_anatomy['trough_date']} (${dd_anatomy['absolute_drop_usd']:,.2f}, {dd_anatomy['pct_retracement']:.2%})
- Recovery: {'%d days' % dd_anatomy['recovery_days'] if dd_anatomy['recovery_days'] else 'Not recovered'}
- US cluster dependency: {us_dependency:.1%} of PnL

## Concentration Risk

- Top contributor accounts for {top_conc:.1%} of total PnL
- US cluster (NAS100, SPX500, US30): ~{us_dependency:.0%} dependency
- Avg pairwise correlation: {corr_data['avg_pairwise_corr']:.3f}

## Regime Performance

"""
    for regime, stats in regime_data['regime'].items():
        overview += f"- **{regime.title()}** vol: {stats['trades']} trades, ${stats['net_pnl']:,.2f} PnL, {stats['win_rate']:.1%} WR\n"

    overview += f"""
## Recommendation

{recommendation}

---
*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Engine: Universal_Research_Engine v{PORTFOLIO_ENGINE_VERSION}*
"""
    return overview


def _snapshot_write_stress_report(strategy_id, stress_results, output_dir):
    """Write stress_test_report.md."""
    stress_md = f"# {strategy_id} - Stress Test Report\n\n"
    stress_md += "| Scenario | Symbols | Net PnL | Sharpe | Max DD | Return/DD |\n"
    stress_md += "|----------|---------|---------|--------|--------|-----------|\n"
    for name, data in stress_results.items():
        stress_md += f"| {name} | {data.get('symbols','?')} | ${data['net_pnl']:,.2f} | {data['sharpe']:.2f} | ${data['max_dd_usd']:,.2f} | {data['return_dd']:.2f} |\n"

    with open(output_dir / 'stress_test_report.md', 'w', encoding='utf-8') as f:
        f.write(stress_md)


def save_snapshot(strategy_id, port_metrics, contributions, corr_data,
                  dd_anatomy, stress_results, regime_data, cap_util, concurrency_data,
                  max_stress_corr, constituent_run_ids, inert_warnings, output_dir):
    """Save frozen evaluation snapshot (orchestrator)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = _snapshot_write_summary_json(
        strategy_id, port_metrics, contributions, corr_data,
        concurrency_data, max_stress_corr, constituent_run_ids,
        inert_warnings, output_dir,
    )
    _snapshot_write_metadata_json(
        strategy_id, contributions, constituent_run_ids, summary, port_metrics, output_dir
    )
    _snapshot_write_metrics_csv(port_metrics, output_dir)

    recommendation, top_conc = _snapshot_recommendation(
        port_metrics, corr_data, contributions, concurrency_data,
    )

    overview = _snapshot_build_overview_md(
        strategy_id, port_metrics, contributions, corr_data,
        dd_anatomy, stress_results, regime_data, cap_util,
        concurrency_data, inert_warnings, recommendation, top_conc,
    )
    with open(output_dir / 'portfolio_overview.md', 'w', encoding='utf-8') as f:
        f.write(overview)

    _snapshot_write_stress_report(strategy_id, stress_results, output_dir)

    print(f"  [SNAPSHOT] Saved to {output_dir}")
    return recommendation
