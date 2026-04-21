"""Strategy-level portfolio report (Stage-5B).

Reads portfolio_summary.json + portfolio_metadata.json only; does NOT touch
the per-symbol CSV artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def generate_strategy_portfolio_report(strategy_name: str, root_dir: Path):
    """
    Generates a deterministic markdown report at the strategy level (Stage-5B).
    Reads ONLY from portfolio evaluation json artifacts.
    """
    # Source data stays in the strategy's portfolio_evaluation directory (read-only)
    source_dir = root_dir / "strategies" / strategy_name / "portfolio_evaluation"
    if not source_dir.exists():
        print(f"[REPORT-WARN] Portfolio evaluation directory missing for {strategy_name}.")
        return

    # Output goes directly to the strategy's root folder
    report_summary_dir = root_dir / "strategies" / strategy_name
    report_summary_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_summary_dir / f"PORTFOLIO_{strategy_name}.md"

    summary_json = source_dir / "portfolio_summary.json"
    metadata_json = source_dir / "portfolio_metadata.json"

    if not summary_json.exists():
        print(f"[REPORT-WARN] portfolio_summary.json missing for {strategy_name}.")
        return

    with open(summary_json, "r", encoding="utf-8") as f:
        summary = json.load(f)

    # Extract date range from portfolio_summary.json data_range field
    start_date = "YYYY-MM-DD"
    end_date = "YYYY-MM-DD"
    data_range = summary.get("data_range", "")
    if " to " in data_range:
        parts = data_range.split(" to ")
        start_date = parts[0].strip()
        end_date = parts[1].strip()

    # Fallback: read metadata if dates are still unresolved
    constituent_runs = []
    evaluated_assets = []
    evaluation_timeframe = summary.get("evaluation_timeframe", "UNKNOWN")
    if metadata_json.exists():
        with open(metadata_json, "r", encoding="utf-8") as f:
            meta = json.load(f)
            if start_date == "YYYY-MM-DD":
                start_date = meta.get("start_date", start_date)
                end_date = meta.get("end_date", end_date)
            constituent_runs = meta.get("constituent_run_ids", [])
            evaluated_assets = meta.get("evaluated_assets", [])
            if "evaluation_timeframe" in meta:
                evaluation_timeframe = meta.get("evaluation_timeframe", evaluation_timeframe)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Explicit key mapping from portfolio_summary.json
    trades = summary.get("total_trades", 0)
    net_pnl = summary.get("net_pnl_usd", 0.0)
    pf = summary.get("profit_factor", 0.0)
    max_dd_pct = summary.get("max_dd_pct", 0.0) * 100  # Convert decimal to percentage
    ret_dd = summary.get("return_dd_ratio", 0.0)
    sharpe = summary.get("sharpe", 0.0)
    sortino = summary.get("sortino", 0.0)
    cagr = summary.get("cagr_pct", 0.0) * 100  # Convert decimal to percentage
    win_rate = summary.get("win_rate", 0.0)
    expectancy = summary.get("expectancy", 0.0)
    avg_corr = summary.get("avg_correlation", 0.0)

    md = [
        f"# Strategy Portfolio Report — {strategy_name}\n",
        f"Date Range: {start_date} → {end_date}",
        f"Execution Timeframe: {evaluation_timeframe}",
        f"Generated: {now_utc}\n",
        "---\n",
        "## Base Model & Assumptions\n",
        "> **Note:** The metrics calculated in this report are based on the **raw (unscaled) runs prior to the application of the capital wrapper**. ",
        "> They represent the pure structural edge of the combined trades without dynamic position sizing applied.\n",
        "---\n",
        "## Portfolio Composition\n",
        "**Constituent Runs:**"
    ]

    if constituent_runs:
        for run_id in constituent_runs:
            md.append(f"- `{run_id}`")
    else:
        md.append("- No constituent runs recorded.")

    md.append("\n**Evaluated Assets:**")
    if evaluated_assets:
        for asset in evaluated_assets:
            md.append(f"- `{asset}`")
    else:
        md.append("- No assets recorded.")

    md.extend([
        "\n---\n",
        "## Portfolio Metrics\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Trades | {trades} |",
        f"| Net PnL | ${net_pnl:.2f} |",
        f"| Win Rate | {win_rate:.1f}% |",
        f"| Profit Factor | {pf:.2f} |",
        f"| Expectancy | ${expectancy:.2f} |",
        f"| Max Drawdown | {max_dd_pct:.2f}% |",
        f"| Return/DD Ratio | {ret_dd:.2f} |",
        f"| CAGR | {cagr:.2f}% |",
        f"| Sharpe Ratio | {sharpe:.2f} |",
        f"| Sortino Ratio | {sortino:.2f} |",
        f"| Avg Correlation | {avg_corr:.4f} |"
    ])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[REPORT] Successfully generated strategy portfolio report: {report_path}")
