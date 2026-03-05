"""
Profile Selector — Step 12: Capital Profile Selection & Ledger Enrichment

Selects the best-performing capital profile (by Return/DD ratio) for each
strategy and enriches the Master Portfolio Sheet with realized execution metrics.

Usage:
    python tools/profile_selector.py <STRATEGY_ID>
    python tools/profile_selector.py --all

Non-authoritative over directive state. Read-only with respect to all
pipeline artifacts except Master_Portfolio_Sheet.xlsx.
"""

import sys
import json
import argparse
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
LEDGER_PATH = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"

# New columns written by this tool
PROFILE_COLUMNS = [
    "deployed_profile",
    "realized_pnl_usd",
    "trades_accepted",
    "trades_rejected",
    "rejection_rate_pct",
    "realized_vs_theoretical_pnl",
]


# ------------------------------------------------------------------
# PROFILE EVALUATION
# ------------------------------------------------------------------
def load_profiles(strategy_id):
    """
    Scan deployable folders for a strategy and load all profile metrics.
    Returns list of (profile_name, metrics_dict).
    """
    deploy_root = STRATEGIES_ROOT / strategy_id / "deployable"
    if not deploy_root.exists():
        return []

    profiles = []
    for profile_dir in sorted(deploy_root.iterdir()):
        if not profile_dir.is_dir():
            continue
        metrics_path = profile_dir / "summary_metrics.json"
        if not metrics_path.exists():
            continue
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            profiles.append((profile_dir.name, metrics))
        except Exception as e:
            print(f"  [WARN] Failed to load {metrics_path}: {e}")
    return profiles


def select_best_profile(profiles):
    """
    Select the profile with the highest Return/DD ratio.
    Return/DD = realized_pnl / max_drawdown_usd
    If max_drawdown_usd is 0, treat as infinity (best possible).
    """
    best_profile = None
    best_ratio = -float("inf")

    for name, metrics in profiles:
        realized = metrics.get("realized_pnl", 0.0)
        max_dd = metrics.get("max_drawdown_usd", 0.0)

        if max_dd == 0:
            ratio = float("inf") if realized > 0 else 0.0
        else:
            ratio = realized / max_dd

        print(f"    {name}: realized_pnl=${realized:,.2f}, "
              f"max_dd=${max_dd:,.2f}, return_dd={ratio:.4f}")

        if ratio > best_ratio:
            best_ratio = ratio
            best_profile = (name, metrics)

    return best_profile


# ------------------------------------------------------------------
# LEDGER UPDATE
# ------------------------------------------------------------------
def enrich_ledger_row(strategy_id, profile_name, profile_metrics, df_ledger):
    """
    Update the Master Portfolio Sheet row for strategy_id with
    profile-aware metrics. Returns the modified DataFrame.
    """
    mask = df_ledger["portfolio_id"].astype(str) == strategy_id
    if not mask.any():
        print(f"  [SKIP] '{strategy_id}' not found in Master Portfolio Sheet")
        return df_ledger

    # Extract values from the winning profile
    realized_pnl = profile_metrics.get("realized_pnl", 0.0)
    accepted = profile_metrics.get("total_accepted", 0)
    rejected = profile_metrics.get("total_rejected", 0)
    rejection_rate = profile_metrics.get("rejection_rate_pct", 0.0)

    # Compute realized vs theoretical ratio
    theoretical_pnl = df_ledger.loc[mask, "net_pnl_usd"].iloc[0]
    if theoretical_pnl and abs(float(theoretical_pnl)) > 0.01:
        ratio = realized_pnl / float(theoretical_pnl)
    else:
        ratio = 0.0

    # Write the 6 new columns
    df_ledger.loc[mask, "deployed_profile"] = profile_name
    df_ledger.loc[mask, "realized_pnl_usd"] = realized_pnl
    df_ledger.loc[mask, "trades_accepted"] = int(accepted)
    df_ledger.loc[mask, "trades_rejected"] = int(rejected)
    df_ledger.loc[mask, "rejection_rate_pct"] = rejection_rate
    df_ledger.loc[mask, "realized_vs_theoretical_pnl"] = round(ratio, 4)

    print(f"  [OK] {strategy_id} -> {profile_name} "
          f"(realized=${realized_pnl:,.2f}, "
          f"accepted={accepted}, rejected={rejected}, "
          f"ratio={ratio:.4f})")

    return df_ledger


# ------------------------------------------------------------------
# COLUMN REORDERING
# ------------------------------------------------------------------

# Logical column groups for readability
COLUMN_ORDER = [
    # ── Identity ──
    "portfolio_id",
    "source_strategy",

    # ── Capital & Performance ──
    "reference_capital_usd",
    "net_pnl_usd",
    "sharpe",
    "max_dd_pct",
    "return_dd_ratio",
    "win_rate",
    "profit_factor",
    "expectancy",
    "total_trades",
    "exposure_pct",
    "equity_stability_k_ratio",

    # ── Deployed Profile ──
    "deployed_profile",
    "realized_pnl_usd",
    "trades_accepted",
    "trades_rejected",
    "rejection_rate_pct",
    "realized_vs_theoretical_pnl",

    # ── Capital Utilization ──
    "peak_capital_deployed",
    "capital_overextension_ratio",

    # ── Concurrency ──
    "avg_concurrent",
    "max_concurrent",
    "p95_concurrent",
    "dd_max_concurrent",
    "full_load_cluster",

    # ── Correlation ──
    "avg_pairwise_corr",
    "max_pairwise_corr_stress",

    # ── Regime Decomposition ──
    "portfolio_net_profit_low_vol",
    "portfolio_net_profit_normal_vol",
    "portfolio_net_profit_high_vol",

    # ── Metadata ──
    "signal_timeframes",
    "evaluation_timeframe",
    "portfolio_engine_version",
    "creation_timestamp",
    "constituent_run_ids",
]


def reorder_columns(df):
    """
    Reorder DataFrame columns to match the logical grouping.
    Any columns not in COLUMN_ORDER are appended at the end.
    """
    existing = df.columns.tolist()
    ordered = [c for c in COLUMN_ORDER if c in existing]
    remaining = [c for c in existing if c not in ordered]
    return df[ordered + remaining]


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def process_strategy(strategy_id, df_ledger):
    """Process a single strategy: load profiles, select best, enrich ledger."""
    print(f"\n[STRATEGY] {strategy_id}")

    profiles = load_profiles(strategy_id)
    if not profiles:
        print(f"  [SKIP] No deployable profiles found")
        return df_ledger

    print(f"  Found {len(profiles)} profile(s): "
          f"{', '.join(p[0] for p in profiles)}")

    best = select_best_profile(profiles)
    if best is None:
        print(f"  [SKIP] No valid profile selected")
        return df_ledger

    profile_name, profile_metrics = best
    print(f"  [SELECTED] {profile_name} (best Return/DD)")

    return enrich_ledger_row(strategy_id, profile_name, profile_metrics,
                             df_ledger)


def main():
    parser = argparse.ArgumentParser(
        description="Profile Selector — Step 12")
    parser.add_argument("strategy_id", nargs="?",
                        help="Strategy ID to process")
    parser.add_argument("--all", action="store_true",
                        help="Process all strategies in the Master Portfolio Sheet")
    args = parser.parse_args()

    if not args.strategy_id and not args.all:
        parser.error("Provide a STRATEGY_ID or use --all")

    # Load ledger
    if not LEDGER_PATH.exists():
        print(f"[FATAL] Master Portfolio Sheet not found: {LEDGER_PATH}")
        sys.exit(1)

    df_ledger = pd.read_excel(LEDGER_PATH)
    print(f"Loaded {len(df_ledger)} rows from Master Portfolio Sheet")

    # Ensure new columns exist
    for col in PROFILE_COLUMNS:
        if col not in df_ledger.columns:
            df_ledger[col] = None

    # Process
    if args.all:
        strategy_ids = df_ledger["portfolio_id"].astype(str).unique().tolist()
        print(f"Processing {len(strategy_ids)} strategies...")
        for sid in strategy_ids:
            df_ledger = process_strategy(sid, df_ledger)
    else:
        df_ledger = process_strategy(args.strategy_id, df_ledger)

    # Reorder columns for readability
    df_ledger = reorder_columns(df_ledger)

    # Save
    df_ledger.to_excel(LEDGER_PATH, index=False)
    print(f"\n[SAVED] {LEDGER_PATH}")
    print("[DONE] Profile selection complete.")


if __name__ == "__main__":
    main()
