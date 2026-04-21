"""Per-profile artifact emission: CSV trade log, equity curve, summary JSON, comparison JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict

from tools.capital.capital_metrics import compute_deployable_metrics
from tools.capital.capital_plotting import plot_equity_curve
from tools.capital.capital_portfolio_state import PortfolioState


def emit_profile_artifacts(state: PortfolioState, output_dir: Path, total_runs: int, total_assets: int):
    """Write per-profile CSV and JSON artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # equity_curve.csv
    with open(output_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "equity"])
        w.writeheader()
        for ts, eq in state.equity_timeline:
            w.writerow({"timestamp": str(ts), "equity": round(eq, 2)})

    # deployable_trade_log.csv
    trade_fields = [
        "trade_id", "symbol", "lot_size", "pnl_usd",
        "entry_timestamp", "exit_timestamp", "direction",
        "entry_price", "exit_price", "risk_distance",
        "initial_stop_price", "atr_entry", "r_multiple",
        "volatility_regime", "trend_regime", "trend_label",
        "signal_hash",   # 16-char SHA-256 prefix for signal integrity verification
    ]

    # Check if overrides exist in log
    has_overrides = any(t.get("risk_override_flag") for t in state.closed_trades_log)
    if has_overrides:
        trade_fields.extend(["risk_override_flag", "target_risk_usd", "actual_risk_usd", "risk_multiple"])

    # Partial-exit columns only emitted when at least one trade carried a partial
    has_partials = any(t.get("partial_fraction") is not None for t in state.closed_trades_log)
    if has_partials:
        trade_fields.extend(["partial_fraction", "partial_pnl_usd", "partial_exit_price", "partial_exit_timestamp"])

    with open(output_dir / "deployable_trade_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=trade_fields, extrasaction='ignore')
        w.writeheader()
        for t in state.closed_trades_log:
            w.writerow(t)

    # rejection_log.csv
    if state.rejection_log:
        rej_fields = list(state.rejection_log[0].keys())
        with open(output_dir / "rejection_log.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rej_fields)
            w.writeheader()
            for r in state.rejection_log:
                w.writerow(r)

    # summary_metrics.json
    metrics = compute_deployable_metrics(state, total_runs, total_assets)
    with open(output_dir / "summary_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # equity_curve.png (equity + drawdown chart)
    plot_equity_curve(state, output_dir)

    print(f"[EMIT] {state.profile_name} artifacts -> {output_dir}")
    return metrics


def emit_comparison_json(all_metrics: Dict[str, dict], states: Dict[str, PortfolioState],
                         output_dir: Path):
    """Write unified profile_comparison.json."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pin RAW_MIN_LOT_V1 first (baseline), then sort the rest alphabetically
    _raw = "RAW_MIN_LOT_V1"
    names = ([_raw] if _raw in all_metrics else []) + sorted(
        [k for k in all_metrics.keys() if k != _raw]
    )
    comparison = {"profiles": {n: all_metrics[n] for n in names}}

    # Acceptance set analysis
    if len(names) == 2:
        a, b = names
        a_set = set(states[a].accepted_trade_ids)
        b_set = set(states[b].accepted_trade_ids)
        comparison["acceptance_analysis"] = {
            "intersection_size": len(a_set & b_set),
            f"exclusive_{a}": len(a_set - b_set),
            f"exclusive_{b}": len(b_set - a_set),
        }
        # Deltas (B - A)
        comparison["deltas"] = {
            "delta_final_equity": round(all_metrics[b]["final_equity"] - all_metrics[a]["final_equity"], 2),
            "delta_max_dd_pct": round(all_metrics[b]["max_drawdown_pct"] - all_metrics[a]["max_drawdown_pct"], 4),
            "delta_cagr_pct": round(all_metrics[b]["cagr_pct"] - all_metrics[a]["cagr_pct"], 4),
        }

    comparison["generated_utc"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    out_path = output_dir / "profile_comparison.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)

    print(f"[EMIT] Comparison -> {out_path}")
    return comparison
