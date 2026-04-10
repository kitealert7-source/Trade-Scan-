"""
Unified Robustness Evaluation CLI (v2.2.0)
Consumes deployable artifacts ONLY: deployable_trade_log.csv, equity_curve.csv,
summary_metrics.json.

Report routing:
    All strategies → strategies/<prefix>/

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
            # Read deployed_profile from ledger (Step 7 is authority).
            import pandas as pd
            from config.state_paths import STRATEGIES_DIR
            ledger = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"
            resolved = None
            if ledger.exists():
                for sheet in ["Portfolios", "Single-Asset Composites"]:
                    try:
                        df = pd.read_excel(ledger, sheet_name=sheet)
                        mask = df["portfolio_id"].astype(str) == str(args.prefix)
                        if mask.any() and "deployed_profile" in df.columns:
                            val = str(df.loc[mask, "deployed_profile"].iloc[-1]).strip()
                            if val and val.lower() != "nan":
                                resolved = val
                                break
                    except Exception:
                        continue
            if resolved:
                print(f"[ROBUSTNESS] Using Step 7 deployed profile: {resolved}")
                args.profile = resolved
            else:
                print(f"[ROBUSTNESS] No deployed_profile in ledger for {args.prefix}. Falling back to CONSERVATIVE_V1")
                args.profile = "CONSERVATIVE_V1"
        except Exception as e:
            print(f"[ROBUSTNESS] Failed to read ledger ({e}). Falling back to CONSERVATIVE_V1")
            args.profile = "CONSERVATIVE_V1"

    print(f"[ROBUSTNESS] Loading artifacts: {args.prefix} / {args.profile}")
    tr_df, eq_df, metrics, all_profiles = load_canonical_artifacts(args.prefix, args.profile, PROJECT_ROOT)
    print(f"[ROBUSTNESS] Loaded {len(tr_df)} trades, {len(eq_df)} equity points")

    run_bootstrap = args.suite == "full"

    # Run central computation layer
    results = run_robustness_suite(
        prefix=args.prefix,
        profile=args.profile,
        tr_df=tr_df,
        eq_df=eq_df,
        metrics=metrics,
        all_profiles=all_profiles,
        run_bootstrap=run_bootstrap
    )
    
    # Generate presentation layer
    report_content = format_report(results, prefix=args.prefix, profile=args.profile)
    report_filename = f"ROBUSTNESS_{args.prefix}_{args.profile}.md"

    # ── Report routing: always save to strategies/<prefix>/ ──
    strategy_dir = STRATEGIES_DIR / args.prefix
    strategy_dir.mkdir(parents=True, exist_ok=True)
    primary_path = strategy_dir / report_filename
    primary_path.write_text(report_content, encoding="utf-8")
    print(f"[ROBUSTNESS] Report saved: {primary_path}")


if __name__ == "__main__":
    main()
