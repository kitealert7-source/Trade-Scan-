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
from tools.profile_selector import load_profile_comparison  # read-only loader
from config.state_paths import STRATEGIES_DIR

STRATEGIES_ROOT = Path(STRATEGIES_DIR)
LEDGER_PATH = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"

# Sheet names in the canonical MPS workbook
SHEET_PORTFOLIOS = "Portfolios"
SHEET_SINGLE_ASSET = "Single-Asset Composites"

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


def _resolve_profile_from_ledger(profiles, deployed_name):
    """Validate that the Step 7 deployed_profile exists in profile_comparison.json.

    Returns (name, metrics, source) or (None, None, None) on failure.
    """
    if not deployed_name or deployed_name.lower() == "nan":
        return None, None, None
    metrics = profiles.get(deployed_name)
    if metrics is None or not isinstance(metrics, dict):
        return None, None, None
    return deployed_name, metrics, "ledger"


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

        # Read Step 7's deployed_profile from ledger — do not re-select.
        deployed_name = None
        if "deployed_profile" in df_ledger.columns:
            raw = str(df_ledger.loc[mask, "deployed_profile"].iloc[-1]).strip()
            if raw and raw.lower() != "nan":
                deployed_name = raw

        profile_name, profile_metrics, source = _resolve_profile_from_ledger(profiles, deployed_name)
        if profile_name is None or profile_metrics is None:
            print(f"[SKIP] {portfolio_id}: deployed_profile '{deployed_name}' not found in profile_comparison.json")
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


def _guard_multi_sheet(path: Path) -> None:
    """Refuse to proceed if the on-disk MPS workbook has collapsed to a single
    unnamed 'Sheet1'. Historically a downstream df.to_excel() overwrote the
    two-sheet MPS with one flat sheet; proceeding from that state would cause
    the DB sync to fan out one sheet's rows into both sheet tags. See
    feedback_db_discipline.md (DB is the source of truth; fail hard on
    structural corruption rather than silently repairing)."""
    if not path.exists():
        return  # fresh install — DB is authoritative, nothing to guard against
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        data_sheets = [s for s in wb.sheetnames if s != "Notes"]
        wb.close()
    except Exception as e:
        print(f"[FATAL] Could not inspect {path.name} for sheet structure: {e}")
        sys.exit(1)
    expected = {SHEET_PORTFOLIOS, SHEET_SINGLE_ASSET}
    if set(data_sheets) != expected:
        print(
            f"[FATAL] {path.name} has data sheets {data_sheets!r}; expected "
            f"{sorted(expected)!r}. Workbook appears collapsed — refusing DB "
            f"sync to avoid duplicating rows across both sheet tags. "
            f"Regenerate via `python -c \"from tools.ledger_db import export_mps; export_mps()\"` "
            f"before re-running reconcile."
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Reconcile Master Portfolio Sheet from profile_comparison.json")
    parser.add_argument("--portfolio", action="append", dest="portfolios", help="Portfolio ID to reconcile (repeatable)")
    args = parser.parse_args()

    # Guard #1 (pre-read): workbook structure must match DB schema assumption.
    _guard_multi_sheet(LEDGER_PATH)

    try:
        from tools.ledger_db import read_mps
        # CRITICAL: read each sheet separately and reconcile independently so
        # sheet membership is preserved. A prior bug merged both into one
        # DataFrame then upserted the union into *both* sheet tags, doubling
        # row counts from 84+63 → 147+147.
        df_port = _ensure_columns(read_mps(sheet=SHEET_PORTFOLIOS))
        df_single = _ensure_columns(read_mps(sheet=SHEET_SINGLE_ASSET))
        if df_port.empty and df_single.empty:
            print(f"[FATAL] Master Portfolio Sheet has no data")
            sys.exit(1)
    except Exception as e:
        print(f"[FATAL] Failed to read Master Portfolio Sheet: {e}")
        sys.exit(1)

    # Route each --portfolio target to the sheet that actually contains it so
    # the other sheet's reconcile pass does not emit spurious "not found" skips.
    port_ids = set(df_port["portfolio_id"].astype(str)) if not df_port.empty else set()
    single_ids = set(df_single["portfolio_id"].astype(str)) if not df_single.empty else set()
    if args.portfolios:
        targets_port = [pid for pid in args.portfolios if pid in port_ids]
        targets_single = [pid for pid in args.portfolios if pid in single_ids]
        unmatched = [pid for pid in args.portfolios if pid not in port_ids and pid not in single_ids]
        for pid in unmatched:
            print(f"[SKIP] {pid}: not found in either sheet of ledger.db")
    else:
        targets_port = None
        targets_single = None

    up_p = sk_p = up_s = sk_s = 0
    if targets_port is None or targets_port:
        df_port, up_p, sk_p = reconcile(df_port, targets_port)
    if targets_single is None or targets_single:
        df_single, up_s, sk_s = reconcile(df_single, targets_single)
    updated = up_p + up_s
    skipped = sk_p + sk_s + (len(unmatched) if args.portfolios else 0)

    df_port = _reorder_columns(df_port)
    df_single = _reorder_columns(df_single)
    if LEGACY_PNL_COL in df_port.columns:
        df_port = df_port.drop(columns=[LEGACY_PNL_COL])
    if LEGACY_PNL_COL in df_single.columns:
        df_single = df_single.drop(columns=[LEGACY_PNL_COL])

    # Guard #2 (pre-sync): the two per-sheet frames must not share portfolio_ids.
    # If they do, someone upstream merged them — refuse to upsert.
    overlap = (set(df_port["portfolio_id"].astype(str))
               & set(df_single["portfolio_id"].astype(str)))
    if overlap:
        print(
            f"[FATAL] Cross-sheet portfolio_id overlap ({len(overlap)} ids, "
            f"e.g. {sorted(overlap)[:3]}). Refusing DB sync — this would "
            f"duplicate rows across both sheet tags."
        )
        sys.exit(1)

    # Write to DB first (single source of truth), then export Excel via
    # ledger_db.export_mps which preserves the two-sheet structure.
    try:
        from tools.ledger_db import _connect, create_tables, upsert_mps_df, export_mps
        _conn = _connect()
        create_tables(_conn)
        upsert_mps_df(_conn, df_port, SHEET_PORTFOLIOS)
        upsert_mps_df(_conn, df_single, SHEET_SINGLE_ASSET)
        _conn.close()
        print(f"  [DB] Synced Portfolios={len(df_port)} + Single-Asset={len(df_single)} row(s) to ledger.db.")
        export_mps()
    except Exception as e:
        print(f"  [FATAL] DB sync/export failed: {e}")
        sys.exit(1)

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
