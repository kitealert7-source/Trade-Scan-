"""
Unified Robustness Evaluation CLI (v2.2.0)
Consumes deployable artifacts ONLY: deployable_trade_log.csv, equity_curve.csv,
summary_metrics.json.

Report routing:
    Multi-asset strategies → strategies/<prefix>/
    Single-asset strategies → backtests/<prefix_SYMBOL>/

Usage:
    python tools/robustness/cli.py <strategy_prefix> \
        --profile CONSERVATIVE_V1 --suite full
"""

import argparse
import json
import sys
from config.state_paths import RUNS_DIR, BACKTESTS_DIR, STRATEGIES_DIR, CANDIDATES_DIR
from pathlib import Path
from datetime import datetime

import pandas as pd

# ── project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.robustness.runner import run_robustness_suite
from tools.robustness.formatter import format_report
from tools.robustness.loader import load_canonical_artifacts

def main():
    parser = argparse.ArgumentParser(description="Unified Robustness Evaluation (v2.2.0)")
    parser.add_argument("prefix", help="Strategy prefix, e.g. AK35_FX_PORTABILITY_4H")
    parser.add_argument("--profile", default="CONSERVATIVE_V1", help="Profile name")
    parser.add_argument("--suite", default="full", choices=["full", "quick"],
                        help="Test suite: full or quick (skips bootstrap)")
    args = parser.parse_args()

    print(f"[ROBUSTNESS] Loading artifacts: {args.prefix} / {args.profile}")
    tr_df, eq_df, metrics = load_canonical_artifacts(args.prefix, args.profile, PROJECT_ROOT)
    print(f"[ROBUSTNESS] Loaded {len(tr_df)} trades, {len(eq_df)} equity points")

    run_bootstrap = args.suite == "full"
    
    # Run central computation layer
    results = run_robustness_suite(
        prefix=args.prefix, 
        profile=args.profile, 
        tr_df=tr_df, 
        eq_df=eq_df, 
        metrics=metrics, 
        run_bootstrap=run_bootstrap
    )
    
    # Generate presentation layer
    report_content = format_report(results, prefix=args.prefix, profile=args.profile)
    report_filename = f"ROBUSTNESS_{args.prefix}_{args.profile}.md"

    # ── Report routing: multi-asset → strategies/, single-asset → backtests/ ──
    unique_symbols = sorted(tr_df["symbol"].unique()) if "symbol" in tr_df.columns else []
    is_single_asset = len(unique_symbols) == 1

    if is_single_asset:
        # Single-asset: save to backtests/<prefix_SYMBOL>/
        symbol = unique_symbols[0]
        backtest_key = f"{args.prefix}_{symbol}"
        primary_dir = BACKTESTS_DIR / backtest_key
        if not primary_dir.exists():
            # Fallback: try without symbol suffix
            primary_dir = BACKTESTS_DIR / args.prefix
        primary_dir.mkdir(parents=True, exist_ok=True)
        primary_path = primary_dir / report_filename
        primary_path.write_text(report_content, encoding="utf-8")
        print(f"[ROBUSTNESS] Single-asset report: {primary_path}")
    else:
        # Multi-asset (portfolio): save to strategies/<prefix>/
        strategy_dir = STRATEGIES_DIR / args.prefix
        if strategy_dir.exists():
            primary_path = strategy_dir / report_filename
            primary_path.write_text(report_content, encoding="utf-8")
            print(f"[ROBUSTNESS] Portfolio report: {primary_path}")
        else:
            print(f"[ROBUSTNESS] WARNING: strategies/{args.prefix}/ not found, skipping primary copy")

    # ── Archive copy (always) ──
    reports_dir = PROJECT_ROOT / "outputs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    archive_path = reports_dir / report_filename
    archive_path.write_text(report_content, encoding="utf-8")
    print(f"[ROBUSTNESS] Archive copy: {archive_path}")


if __name__ == "__main__":
    main()
