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
from config.state_paths import RUNS_DIR, BACKTESTS_DIR, STRATEGIES_DIR, SELECTED_DIR
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
    parser.add_argument("--profile", default="auto", help="Profile name or 'auto' to read from best origin profile")
    parser.add_argument("--suite", default="full", choices=["full", "quick"],
                        help="Test suite: full or quick (skips bootstrap)")
    args = parser.parse_args()

    if args.profile == "auto":
        try:
            from tools.profile_selector import load_profile_comparison, select_deployed_profile
            profiles, path = load_profile_comparison(args.prefix)
            if profiles:
                best_name, _, source = select_deployed_profile(profiles)
                if best_name:
                    print(f"[ROBUSTNESS] Auto-selected profile: {best_name} (Origin: {source})")
                    args.profile = best_name
                else:
                    print("[ROBUSTNESS] Failed to resolve auto profile. Falling back to CONSERVATIVE_V1")
                    args.profile = "CONSERVATIVE_V1"
            else:
                print(f"[ROBUSTNESS] No profile_comparison.json found for {args.prefix}. Falling back to CONSERVATIVE_V1")
                args.profile = "CONSERVATIVE_V1"
        except ImportError as e:
            print(f"[ROBUSTNESS] Failed to load auto profile dependencies ({e}). Falling back to CONSERVATIVE_V1")
            args.profile = "CONSERVATIVE_V1"

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
        # Multi-asset (portfolio): save exclusively to strategies/<prefix>/
        strategy_dir = STRATEGIES_DIR / args.prefix
        strategy_dir.mkdir(parents=True, exist_ok=True)
        primary_path = strategy_dir / report_filename
        primary_path.write_text(report_content, encoding="utf-8")
        print(f"[ROBUSTNESS] Portfolio report: {primary_path}")


if __name__ == "__main__":
    main()
