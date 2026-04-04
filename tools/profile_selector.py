"""
Profile Selector - Step 8.5: Ledger enrichment from profile_comparison.json.

Usage:
    python tools/profile_selector.py <STRATEGY_ID>
    python tools/profile_selector.py --all
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.state_paths import STRATEGIES_DIR
from config.status_enums import PORTFOLIO_PROFILE_UNRESOLVED
STRATEGIES_ROOT = STRATEGIES_DIR
LEDGER_PATH = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"

LEDGER_PNL_COL = "realized_pnl"
LEGACY_PNL_COL = "net_pnl_usd"

PROFILE_COLUMNS = [
    "deployed_profile",
    "theoretical_pnl",
    "realized_pnl",
    "realized_pnl_usd",
    "trades_accepted",
    "trades_rejected",
    "rejection_rate_pct",
    "realized_vs_theoretical_pnl",
]


def _safe_float(value, default=0.0):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _profile_return_dd(metrics):
    realized = _safe_float(metrics.get("realized_pnl"), 0.0)
    max_dd = abs(_safe_float(metrics.get("max_drawdown_usd"), 0.0))
    if max_dd <= 1e-12:
        return float("inf") if realized > 0 else 0.0
    return realized / max_dd


def load_profile_comparison(strategy_id):
    """Load profile_comparison.json and return profile map."""
    path = STRATEGIES_ROOT / strategy_id / "deployable" / "profile_comparison.json"
    if not path.exists():
        return None, path

    # Post-process to inject real capital metrics dynamically
    try:
        from tools.post_process_capital import process_profile_comparison
        process_profile_comparison(strategy_id)
    except Exception as e:
        print(f"  [WARN] Failed to post-process real metrics for {strategy_id}: {e}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] Failed to parse {path}: {e}")
        return None, path

    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        print(f"  [WARN] Invalid schema in {path}: missing non-empty 'profiles'.")
        return None, path

    return profiles, path


def select_deployed_profile(profiles, preferred_name=None):
    """
    Resolve deployed profile:
      1) Best Return/DD from profile comparison.
    """
    best_name = None
    best_metrics = None
    best_key = (-float("inf"), -float("inf"), "")

    for name, metrics in profiles.items():
        if not isinstance(metrics, dict):
            continue
            
        avg_risk = _safe_float(metrics.get("avg_risk_multiple"), 0.0)
        if avg_risk > 1.5:
            continue

        score = _profile_return_dd(metrics)
        realized = _safe_float(metrics.get("realized_pnl"), 0.0)
        key = (score, realized, name)
        if key > best_key:
            best_key = key
            best_name = name
            best_metrics = metrics

    return best_name, best_metrics, "best_return_dd"


def ensure_ledger_columns(df_ledger):
    """Backfill renamed columns and ensure profile columns exist."""
    if LEDGER_PNL_COL not in df_ledger.columns and LEGACY_PNL_COL in df_ledger.columns:
        df_ledger[LEDGER_PNL_COL] = df_ledger[LEGACY_PNL_COL]
    if "theoretical_pnl" not in df_ledger.columns:
        if LEGACY_PNL_COL in df_ledger.columns:
            df_ledger["theoretical_pnl"] = pd.to_numeric(df_ledger[LEGACY_PNL_COL], errors="coerce")
        else:
            df_ledger["theoretical_pnl"] = pd.to_numeric(df_ledger.get(LEDGER_PNL_COL), errors="coerce")

    for col in PROFILE_COLUMNS:
        if col not in df_ledger.columns:
            df_ledger[col] = None
    if "realized_vs_theoretical_pnl" in df_ledger.columns:
        df_ledger["realized_vs_theoretical_pnl"] = pd.to_numeric(
            df_ledger["realized_vs_theoretical_pnl"], errors="coerce"
        )

    return df_ledger


def enrich_ledger_row(strategy_id, df_ledger):
    mask = df_ledger["portfolio_id"].astype(str) == str(strategy_id)
    if not mask.any():
        print(f"  [SKIP] '{strategy_id}' not found in Master Portfolio Sheet")
        return df_ledger

    profiles, path = load_profile_comparison(strategy_id)
    if profiles is None:
        print(f"  [SKIP] Missing/invalid profile comparison: {path}")
        return df_ledger

    # Step 8.5 is a VALIDATOR / ENRICHER — it does NOT re-select the profile.
    # The authoritative profile choice is made by portfolio_evaluator.py (Step 7).
    # We read the already-chosen profile from the ledger and enrich metrics only.
    #
    # Fallback rule: only trigger when the deployed_profile column is explicitly
    # absent (column missing or cell is pandas NaN/None).  If Step 7 wrote
    # *anything* — even an unexpected value — Step 8.5 must respect it.
    # This prevents hidden divergence from partial writes or bugs.
    profile_name = None
    step7_wrote_something = False
    if "deployed_profile" in df_ledger.columns:
        raw_val = df_ledger.loc[mask, "deployed_profile"].iloc[-1]
        if pd.notna(raw_val):
            existing_raw = str(raw_val).strip()
            if existing_raw and existing_raw.lower() != "nan":
                profile_name = existing_raw
                step7_wrote_something = True

    # Fallback ONLY when Step 7 genuinely didn't write a profile (column absent
    # or cell is NaN).  This is the single-asset skip path.  If Step 7 wrote
    # something invalid, we skip — do NOT silently override with different logic.
    if profile_name is None:
        if step7_wrote_something:
            # Step 7 wrote something but it resolved to empty/invalid — don't override.
            # Mark the row explicitly so operators see this in the ledger, not just logs.
            print(f"  [ERROR] Step 7 wrote an unresolvable deployed_profile for {strategy_id} — not overriding")
            print(f"  [ERROR] Ledger row will have incomplete profile metrics. Manual review required.")
            if "portfolio_status" in df_ledger.columns:
                df_ledger.loc[mask, "portfolio_status"] = PORTFOLIO_PROFILE_UNRESOLVED
            return df_ledger
        profile_name, _, source = select_deployed_profile(profiles)
        if profile_name is None:
            print("  [SKIP] Could not resolve deployed profile (no Step 7 selection, fallback also failed)")
            return df_ledger
        print(f"  [FALLBACK] No Step 7 profile found — selected {profile_name} via fallback ({source})")

    profile_metrics = profiles.get(profile_name)
    if profile_metrics is None or not isinstance(profile_metrics, dict):
        print(f"  [SKIP] Profile '{profile_name}' not found in profile_comparison.json")
        return df_ledger

    realized = round(_safe_float(profile_metrics.get("realized_pnl"), 0.0), 2)
    accepted = int(round(_safe_float(profile_metrics.get("total_accepted"), 0.0)))
    rejected = int(round(_safe_float(profile_metrics.get("total_rejected"), 0.0)))
    rejection_rate = round(_safe_float(profile_metrics.get("rejection_rate_pct"), 0.0), 2)

    theoretical_base = _safe_float(df_ledger.loc[mask, "theoretical_pnl"].iloc[-1], 0.0)
    if abs(theoretical_base) <= 1e-12 and LEGACY_PNL_COL in df_ledger.columns:
        theoretical_base = _safe_float(df_ledger.loc[mask, LEGACY_PNL_COL].iloc[-1], 0.0)

    if abs(theoretical_base) > 1e-12:
        ratio = round(realized / theoretical_base, 4)
    else:
        ratio = 1.0 if abs(realized) > 1e-12 else 0.0

    df_ledger.loc[mask, "deployed_profile"] = profile_name
    df_ledger.loc[mask, LEDGER_PNL_COL] = realized
    df_ledger.loc[mask, "realized_pnl_usd"] = realized
    df_ledger.loc[mask, "trades_accepted"] = accepted
    df_ledger.loc[mask, "trades_rejected"] = rejected
    df_ledger.loc[mask, "rejection_rate_pct"] = rejection_rate
    df_ledger.loc[mask, "realized_vs_theoretical_pnl"] = ratio

    # --- Fix 1: Recompute portfolio_status with actual profile data ---
    # Stage-4 writes status before capital wrapper runs, so it's always FAIL.
    # Now we have the real realized_pnl and trades_accepted from the deployed profile.
    from tools.portfolio_evaluator import _compute_portfolio_status
    new_status = _compute_portfolio_status(realized, accepted, rejection_rate)
    old_status = str(df_ledger.loc[mask, "portfolio_status"].iloc[-1])
    if "portfolio_status" in df_ledger.columns:
        df_ledger.loc[mask, "portfolio_status"] = new_status
    if old_status != new_status:
        print(f"  [STATUS] {old_status} -> {new_status}")

    # --- Fix 2: Update reference_capital_usd from deployed profile ---
    # effective_capital = max_concurrent_trades × $1,000 per asset.
    # This is the real capital footprint, not the $10,000 simulation pool.
    effective_capital = _safe_float(profile_metrics.get("effective_capital"), 0.0)
    if effective_capital <= 0:
        # Fallback: check capital_insights block
        effective_capital = _safe_float(
            profile_metrics.get("capital_insights", {}).get("effective_capital", 0.0),
            0.0,
        )
    if effective_capital > 0 and "reference_capital_usd" in df_ledger.columns:
        df_ledger.loc[mask, "reference_capital_usd"] = effective_capital

    # --- Fix 3: Recompute profile_trade_density with actual rejection rate ---
    # Stage-4 computes this before capital wrapper, so rejection_rate is None.
    if "trade_density" in df_ledger.columns and "profile_trade_density" in df_ledger.columns:
        td_raw = _safe_float(df_ledger.loc[mask, "trade_density"].iloc[-1], 0.0)
        if td_raw > 0 and rejection_rate > 0:
            profile_td = int(round(td_raw * (1.0 - rejection_rate / 100.0)))
            df_ledger.loc[mask, "profile_trade_density"] = profile_td

    print(
        f"  [OK] {strategy_id} -> {profile_name} (enriched) "
        f"realized=${realized:,.2f}, accepted={accepted}, rejected={rejected}, ratio={ratio:.4f}"
    )
    return df_ledger


COLUMN_ORDER = [
    "portfolio_id",
    "source_strategy",

    "reference_capital_usd",
    "trade_density",
    "profile_trade_density",
    "theoretical_pnl",
    "realized_pnl",
    "sharpe",
    "max_dd_pct",
    "return_dd_ratio",
    "win_rate",
    "profit_factor",
    "expectancy",
    "total_trades",
    "exposure_pct",
    "equity_stability_k_ratio",

    "deployed_profile",
    "realized_pnl_usd",
    "trades_accepted",
    "trades_rejected",
    "rejection_rate_pct",
    "realized_vs_theoretical_pnl",

    "peak_capital_deployed",
    "capital_overextension_ratio",

    "avg_concurrent",
    "max_concurrent",
    "p95_concurrent",
    "dd_max_concurrent",
    "full_load_cluster",

    "avg_pairwise_corr",
    "max_pairwise_corr_stress",

    "portfolio_net_profit_low_vol",
    "portfolio_net_profit_normal_vol",
    "portfolio_net_profit_high_vol",

    "signal_timeframes",
    "evaluation_timeframe",
    "portfolio_engine_version",
    "creation_timestamp",
    "constituent_run_ids",
]


def reorder_columns(df):
    existing = df.columns.tolist()
    ordered = [c for c in COLUMN_ORDER if c in existing]
    remaining = [c for c in existing if c not in ordered]
    return df[ordered + remaining]


def process_strategy(strategy_id, df_ledger):
    print(f"\n[STRATEGY] {strategy_id}")
    return enrich_ledger_row(strategy_id, df_ledger)


def main():
    parser = argparse.ArgumentParser(description="Profile Selector - Step 8.5")
    parser.add_argument("strategy_id", nargs="?", help="Strategy ID to process")
    parser.add_argument("--all", action="store_true", help="Process all strategies in Master Portfolio Sheet")
    args = parser.parse_args()

    if not args.strategy_id and not args.all:
        parser.error("Provide a STRATEGY_ID or use --all")

    if not LEDGER_PATH.exists():
        print(f"[FATAL] Master Portfolio Sheet not found: {LEDGER_PATH}")
        sys.exit(1)

    df_ledger = pd.read_excel(LEDGER_PATH)
    df_ledger = ensure_ledger_columns(df_ledger)
    print(f"Loaded {len(df_ledger)} rows from Master Portfolio Sheet")

    if args.all:
        strategy_ids = df_ledger["portfolio_id"].astype(str).unique().tolist()
        print(f"Processing {len(strategy_ids)} strategies...")
        for sid in strategy_ids:
            df_ledger = process_strategy(sid, df_ledger)
    else:
        df_ledger = process_strategy(args.strategy_id, df_ledger)

    df_ledger = reorder_columns(df_ledger)

    # Remove legacy column after migration to keep naming clear.
    if LEGACY_PNL_COL in df_ledger.columns:
        df_ledger = df_ledger.drop(columns=[LEGACY_PNL_COL])

    df_ledger.to_excel(LEDGER_PATH, index=False)
    print(f"\n[SAVED] {LEDGER_PATH}")

    # Reapply formatting — to_excel() strips all Excel styles.
    try:
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "format_excel_artifact.py"),
             "--file", str(LEDGER_PATH), "--profile", "portfolio"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Formatting failed: {e}")

    print("[DONE] Profile selection complete.")


if __name__ == "__main__":
    main()
