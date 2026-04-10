"""
Profile Selector - Step 8.5: Validate & enrich ledger from profile_comparison.json.

Does NOT select profiles.  Step 7 (portfolio_evaluator.py) is the sole
authority for deployed_profile.  This tool reads Step 7's choice from the
ledger and enriches metrics (realized_pnl, trades, rejection rate, status).

Usage:
    python tools/profile_selector.py <STRATEGY_ID>
    python tools/profile_selector.py --all
"""

import sys
import hashlib
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


def _file_hash(path):
    """SHA-256 of file contents (fast, deterministic)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_profile_comparison(strategy_id):
    """Load profile_comparison.json and return profile map.

    Pure read — no disk mutation.  ``post_process_capital`` is intentionally
    NOT called here; it is a separate pipeline step that enriches the JSON
    *once* after capital-wrapper finishes, not on every read.
    """
    path = STRATEGIES_ROOT / strategy_id / "deployable" / "profile_comparison.json"
    if not path.exists():
        return None, path

    hash_before = _file_hash(path)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] Failed to parse {path}: {e}")
        return None, path

    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        print(f"  [WARN] Invalid schema in {path}: missing non-empty 'profiles'.")
        return None, path

    # Determinism guard: file must not have been mutated during read.
    hash_after = _file_hash(path)
    if hash_before != hash_after:
        print(f"  [ERROR] NON_DETERMINISTIC_INPUT_DETECTED: {path.name} "
              f"was mutated during load for {strategy_id}")

    return profiles, path


def select_deployed_profile(profiles, preferred_name=None):
    """DEPRECATED — do not use for ledger decisions.

    Step 7 (_resolve_deployed_profile in portfolio_evaluator.py) is the sole
    authority for deployed_profile selection.  This function exists only as a
    legacy helper; no pipeline path should call it for profile selection.
    """
    raise RuntimeError("DEPRECATED: Selection is handled in Step 7 only.")


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

    # Step 8.5 is a VALIDATOR / ENRICHER only.
    # The authoritative profile choice is made by Step 7 (portfolio_evaluator.py).
    # We read the already-chosen profile from the ledger and enrich metrics.
    profile_name = None
    if "deployed_profile" in df_ledger.columns:
        raw_val = df_ledger.loc[mask, "deployed_profile"].iloc[-1]
        if pd.notna(raw_val):
            token = str(raw_val).strip()
            if token and token.lower() != "nan":
                profile_name = token

    if profile_name is None:
        print(f"  [SKIP] No deployed_profile set by Step 7 for {strategy_id}")
        if "portfolio_status" in df_ledger.columns:
            df_ledger.loc[mask, "portfolio_status"] = PORTFOLIO_PROFILE_UNRESOLVED
        return df_ledger

    # Invariant: selected profile must exist in profile_comparison.json.
    # Catches stale references, deleted/renamed profiles, legacy leakage.
    profile_metrics = profiles.get(profile_name)
    if profile_metrics is None or not isinstance(profile_metrics, dict):
        available = sorted(k for k, v in profiles.items() if isinstance(v, dict))
        print(f"  [INVARIANT VIOLATION] deployed_profile '{profile_name}' not found in "
              f"profile_comparison.json for {strategy_id}")
        print(f"  [INVARIANT VIOLATION] Available profiles: {available}")
        if "portfolio_status" in df_ledger.columns:
            df_ledger.loc[mask, "portfolio_status"] = PORTFOLIO_PROFILE_UNRESOLVED
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
    df_ledger.loc[mask, "trades_accepted"] = accepted
    df_ledger.loc[mask, "trades_rejected"] = rejected
    df_ledger.loc[mask, "rejection_rate_pct"] = rejection_rate
    df_ledger.loc[mask, "realized_vs_theoretical_pnl"] = ratio

    # portfolio_status: OWNED BY Step 7 — do not recompute here.

    # reference_capital_usd: OWNED BY Step 7 — do not overwrite here.

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


def reorder_columns(df):
    existing = df.columns.tolist()
    ordered = [c for c in COLUMN_ORDER if c in existing]
    remaining = [c for c in existing if c not in ordered]
    return df[ordered + remaining]


def process_strategy(strategy_id, df_ledger):
    print(f"\n[STRATEGY] {strategy_id}")
    return enrich_ledger_row(strategy_id, df_ledger)


_DATA_SHEETS = ["Portfolios", "Single-Asset Composites"]


def _load_sheet_dfs(ledger_path):
    """Load all data sheets from the ledger into {sheet_name: df}.

    Handles both the two-tab format ("Portfolios" / "Single-Asset Composites")
    and the legacy single-tab format ("Sheet1").  Never reads a non-data sheet
    (e.g. Notes) as a data frame.
    """
    sheet_dfs = {}
    with pd.ExcelFile(ledger_path) as xls:
        available = xls.sheet_names
        for s in _DATA_SHEETS:
            if s in available:
                sheet_dfs[s] = pd.read_excel(xls, sheet_name=s)
        if not sheet_dfs:
            # Legacy single-sheet workbook — load first non-Notes sheet.
            for s in available:
                if s != "Notes":
                    # Route legacy Sheet1 data to Portfolios tab on next save.
                    sheet_dfs["Portfolios"] = pd.read_excel(xls, sheet_name=s)
                    print(f"[MIGRATE] Legacy sheet '{s}' loaded as 'Portfolios'")
                    break
    return sheet_dfs


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

    # Load all data sheets (preserves two-tab structure).
    sheet_dfs = _load_sheet_dfs(LEDGER_PATH)
    total_rows = sum(len(df) for df in sheet_dfs.values())
    print(f"Loaded {total_rows} rows from Master Portfolio Sheet "
          f"({', '.join(f'{s}: {len(df)}' for s, df in sheet_dfs.items())})")

    for s in list(sheet_dfs):
        sheet_dfs[s] = ensure_ledger_columns(sheet_dfs[s])

    if args.all:
        for s, df in sheet_dfs.items():
            strategy_ids = df["portfolio_id"].astype(str).unique().tolist()
            print(f"Processing {len(strategy_ids)} strategies in '{s}'...")
            for sid in strategy_ids:
                sheet_dfs[s] = process_strategy(sid, sheet_dfs[s])
    else:
        sid = args.strategy_id
        found = False
        for s, df in sheet_dfs.items():
            if str(sid) in df["portfolio_id"].astype(str).values:
                sheet_dfs[s] = process_strategy(sid, sheet_dfs[s])
                found = True
                break
        if not found:
            print(f"[SKIP] '{sid}' not found in any data sheet")

    for s in list(sheet_dfs):
        sheet_dfs[s] = reorder_columns(sheet_dfs[s])
        if LEGACY_PNL_COL in sheet_dfs[s].columns:
            sheet_dfs[s] = sheet_dfs[s].drop(columns=[LEGACY_PNL_COL])

    # Write all sheets back — preserves two-tab structure AND non-data sheets
    # (e.g. Notes). Previous bug: mode='w' with only data sheets deleted Notes.
    _preserve = {}
    if LEDGER_PATH.exists():
        with pd.ExcelFile(LEDGER_PATH) as _xls:
            for _sn in _xls.sheet_names:
                if _sn not in sheet_dfs:
                    try:
                        _preserve[_sn] = pd.read_excel(_xls, sheet_name=_sn)
                    except Exception:
                        pass
    with pd.ExcelWriter(LEDGER_PATH, engine="openpyxl", mode="w") as writer:
        for s, df in sheet_dfs.items():
            df.to_excel(writer, sheet_name=s, index=False)
        for _sn, _sdf in _preserve.items():
            _sdf.to_excel(writer, sheet_name=_sn, index=False)
    print(f"\n[SAVED] {LEDGER_PATH}")

    _formatter = Path(__file__).parent / "format_excel_artifact.py"
    try:
        subprocess.run(
            [sys.executable, str(_formatter), "--file", str(LEDGER_PATH), "--profile", "portfolio"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Formatting failed: {e}")

    try:
        subprocess.run(
            [sys.executable, str(_formatter), "--file", str(LEDGER_PATH), "--notes-type", "portfolio"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Notes update failed: {e}")

    # End-of-run visibility: count unresolved rows across all sheets.
    unresolved = 0
    for s, df in sheet_dfs.items():
        if "portfolio_status" in df.columns:
            unresolved += (df["portfolio_status"].astype(str) == "PROFILE_UNRESOLVED").sum()
    if unresolved > 0:
        print(f"[WARNING] UNRESOLVED_PROFILES: {unresolved}")

    print("[DONE] Profile selection complete.")


if __name__ == "__main__":
    main()
