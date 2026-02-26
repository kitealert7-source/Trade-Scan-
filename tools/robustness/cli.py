"""
Unified Robustness Evaluation CLI (v2.1.1)
Consumes deployable artifacts ONLY: deployable_trade_log.csv, equity_curve.csv,
summary_metrics.json.

Usage:
    python tools/robustness/cli.py <strategy_prefix> \
        --profile CONSERVATIVE_V1 --suite full
"""

import argparse
import json
import sys
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
    parser = argparse.ArgumentParser(description="Unified Robustness Evaluation (v2.1.1)")
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

    # Write report — outputs/reports/ (archive copy)
    reports_dir = PROJECT_ROOT / "outputs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"ROBUSTNESS_{args.prefix}_{args.profile}.md"
    report_path.write_text(report_content, encoding="utf-8")
    print(f"[ROBUSTNESS] Report written: {report_path}")

    # Write report — strategies/<prefix>/ (strategy root)
    strategy_dir = PROJECT_ROOT / "strategies" / args.prefix
    if strategy_dir.exists():
        strategy_report = strategy_dir / f"ROBUSTNESS_{args.prefix}_{args.profile}.md"
        strategy_report.write_text(report_content, encoding="utf-8")
        print(f"[ROBUSTNESS] Strategy copy: {strategy_report}")


if __name__ == "__main__":
    main()
