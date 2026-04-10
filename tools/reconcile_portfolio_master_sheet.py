"""
Reconcile Master_Portfolio_Sheet.xlsx from deployable profile_comparison.json.

Purpose:
- Patch existing ledger rows without rerunning pipelines.
- Overwrite realized PnL and accepted/rejected counts from deployed profile.
- Migrate legacy net_pnl_usd column name to realized_pnl.

Usage:
    python tools/reconcile_portfolio_master_sheet.py
    python tools/reconcile_portfolio_master_sheet.py --portfolio IDX22
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from tools.profile_selector import select_deployed_profile  # single source of truth

STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
LEDGER_PATH = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"

LEDGER_PNL_COL = "realized_pnl"
LEGACY_PNL_COL = "net_pnl_usd"

COLUMN_ORDER = [
    "portfolio_id",
    "source_strategy",
    "reference_capital_usd",
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
    "edge_quality",
    "sqn",
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
    "evaluation_timeframe",
    "portfolio_engine_version",
    "creation_timestamp",
    "constituent_run_ids",
]


def _safe_float(value, default=0.0):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _load_profile_map(portfolio_id):
    path = STRATEGIES_ROOT / portfolio_id / "deployable" / "profile_comparison.json"
    if not path.exists():
        return None, path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] {portfolio_id}: failed to parse {path.name}: {e}")
        return None, path
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        print(f"  [WARN] {portfolio_id}: invalid profile_comparison.json (missing profiles)")
        return None, path
    return profiles, path


def _select_profile(portfolio_id, profiles, deployed_hint):
    # Respect Step 7's existing choice if present in profile data.
    if deployed_hint and deployed_hint in profiles:
        return deployed_hint, profiles[deployed_hint], "ledger"

    # Fallback: delegate to the single canonical selector (includes avg_risk_multiple gate).
    return select_deployed_profile(profiles)


def _ensure_columns(df):
    if LEDGER_PNL_COL not in df.columns and LEGACY_PNL_COL in df.columns:
        df[LEDGER_PNL_COL] = df[LEGACY_PNL_COL]
    if "theoretical_pnl" not in df.columns:
        if LEGACY_PNL_COL in df.columns:
            df["theoretical_pnl"] = pd.to_numeric(df[LEGACY_PNL_COL], errors="coerce")
        else:
            df["theoretical_pnl"] = pd.to_numeric(df.get(LEDGER_PNL_COL), errors="coerce")

    required = [
        "deployed_profile",
        "theoretical_pnl",
        "realized_pnl",
        "trades_accepted",
        "trades_rejected",
        "rejection_rate_pct",
        "realized_vs_theoretical_pnl",
    ]
    for col in required:
        if col not in df.columns:
            df[col] = None
    if "realized_vs_theoretical_pnl" in df.columns:
        df["realized_vs_theoretical_pnl"] = pd.to_numeric(
            df["realized_vs_theoretical_pnl"], errors="coerce"
        )
    return df


def reconcile(df_ledger, target_portfolios=None):
    updated = 0
    skipped = 0

    if target_portfolios:
        portfolio_ids = target_portfolios
    else:
        portfolio_ids = df_ledger["portfolio_id"].astype(str).unique().tolist()

    for portfolio_id in portfolio_ids:
        mask = df_ledger["portfolio_id"].astype(str) == str(portfolio_id)
        if not mask.any():
            print(f"[SKIP] {portfolio_id}: not found in ledger")
            skipped += 1
            continue

        # Guard: do not reconcile rows with unresolved/blocked status.
        if "portfolio_status" in df_ledger.columns:
            status = str(df_ledger.loc[mask, "portfolio_status"].iloc[-1]).strip()
            if status in ("PROFILE_UNRESOLVED", "FAIL"):
                print(f"[SKIP] {portfolio_id}: portfolio_status={status} — not reconciling")
                skipped += 1
                continue

        profiles, profile_path = _load_profile_map(portfolio_id)
        if profiles is None:
            print(f"[SKIP] {portfolio_id}: missing/invalid {profile_path}")
            skipped += 1
            continue

        deployed_hint = None
        if "deployed_profile" in df_ledger.columns:
            raw = str(df_ledger.loc[mask, "deployed_profile"].iloc[-1]).strip()
            if raw and raw.lower() != "nan":
                deployed_hint = raw

        profile_name, profile_metrics, source = _select_profile(portfolio_id, profiles, deployed_hint)
        if profile_name is None or profile_metrics is None:
            print(f"[SKIP] {portfolio_id}: could not resolve deployed profile")
            skipped += 1
            continue

        realized = round(_safe_float(profile_metrics.get("realized_pnl"), 0.0), 2)
        accepted = int(round(_safe_float(profile_metrics.get("total_accepted"), 0.0)))
        rejected = int(round(_safe_float(profile_metrics.get("total_rejected"), 0.0)))
        rejection_rate = round(_safe_float(profile_metrics.get("rejection_rate_pct"), 0.0), 2)

        theoretical = _safe_float(df_ledger.loc[mask, "theoretical_pnl"].iloc[-1], 0.0)
        if abs(theoretical) <= 1e-12 and LEGACY_PNL_COL in df_ledger.columns:
            theoretical = _safe_float(df_ledger.loc[mask, LEGACY_PNL_COL].iloc[-1], 0.0)
        if abs(theoretical) > 1e-12:
            ratio = round(realized / theoretical, 4)
        else:
            ratio = 1.0 if abs(realized) > 1e-12 else 0.0

        df_ledger.loc[mask, "deployed_profile"] = profile_name
        df_ledger.loc[mask, LEDGER_PNL_COL] = realized
        df_ledger.loc[mask, "trades_accepted"] = accepted
        df_ledger.loc[mask, "trades_rejected"] = rejected
        df_ledger.loc[mask, "rejection_rate_pct"] = rejection_rate
        df_ledger.loc[mask, "realized_vs_theoretical_pnl"] = ratio

        print(
            f"[OK] {portfolio_id}: {profile_name} ({source}) "
            f"realized=${realized:,.2f}, accepted={accepted}, rejected={rejected}, ratio={ratio:.4f}"
        )
        updated += 1

    return df_ledger, updated, skipped


def _reorder_columns(df):
    existing = df.columns.tolist()
    ordered = [c for c in COLUMN_ORDER if c in existing]
    remaining = [c for c in existing if c not in ordered]
    return df[ordered + remaining]


def main():
    parser = argparse.ArgumentParser(description="Reconcile Master Portfolio Sheet from profile_comparison.json")
    parser.add_argument("--portfolio", action="append", dest="portfolios", help="Portfolio ID to reconcile (repeatable)")
    args = parser.parse_args()

    if not LEDGER_PATH.exists():
        print(f"[FATAL] Master Portfolio Sheet not found: {LEDGER_PATH}")
        sys.exit(1)

    df_ledger = pd.read_excel(LEDGER_PATH)
    df_ledger = _ensure_columns(df_ledger)

    df_ledger, updated, skipped = reconcile(df_ledger, args.portfolios)
    df_ledger = _reorder_columns(df_ledger)

    if LEGACY_PNL_COL in df_ledger.columns:
        df_ledger = df_ledger.drop(columns=[LEGACY_PNL_COL])

    df_ledger.to_excel(LEDGER_PATH, index=False)

    try:
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "format_excel_artifact.py"),
            "--file", str(LEDGER_PATH),
            "--profile", "portfolio",
        ]
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Formatting failed: {e}")

    print(f"\n[DONE] Updated: {updated} | Skipped: {skipped}")


if __name__ == "__main__":
    main()
