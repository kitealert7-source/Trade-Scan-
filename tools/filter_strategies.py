import pandas as pd
import openpyxl
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import MASTER_FILTER_PATH, POOL_DIR, RUNS_DIR, CANDIDATE_FILTER_PATH
from tools.system_registry import _load_registry, _save_registry_atomic

MASTER_SHEET = MASTER_FILTER_PATH

# TS_Execution portfolio.yaml — source of truth for BURN_IN status.
# Strategies listed here with enabled=true get BURN_IN; removal reverts to computed status.
_TS_EXEC_PORTFOLIO = PROJECT_ROOT.parent / "TS_Execution" / "portfolio.yaml"


def _load_burnin_ids() -> set[str]:
    """Read enabled strategy IDs from TS_Execution/portfolio.yaml.

    Returns a set of strategy IDs (e.g. '22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P04_USDCAD').
    Silent on any error — missing file or parse failure returns empty set.
    """
    try:
        import yaml
        if not _TS_EXEC_PORTFOLIO.exists():
            return set()
        with open(_TS_EXEC_PORTFOLIO, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        strategies = (data.get("portfolio") or {}).get("strategies") or []
        ids = set()
        for s in strategies:
            if s.get("enabled", True) and "id" in s:
                ids.add(s["id"])
        return ids
    except Exception as e:
        print(f"[WARN] Could not load BURN_IN IDs from portfolio.yaml: {e}")
        return set()


def _compute_candidate_status(df: pd.DataFrame) -> pd.Series:
    """
    Deterministic classification for candidate ledger rows:
      BURN_IN : strategy is in TS_Execution/portfolio.yaml (enabled=true)
      FAIL    : total_trades < 50 OR max_dd_pct > 40 OR sqn < 1.5
                OR expectancy below asset-class FAIL gate
      CORE    : total_trades >= 200 AND return_dd_ratio >= 2.0 AND sharpe_ratio >= 1.5
                AND sqn >= 2.5 AND max_dd_pct <= 30 AND trade_density >= 50
                AND profit_factor >= 1.25
      WATCH   : otherwise

    Expectancy gates (logic-driven, calibrated 2026-04-07):
      Backtests include spread (baked into OHLC). Only slippage is unmodeled.
      Slippage cost proportional to spread; non-FX has ~3.3x higher friction
      per lot (derived from OctaFX broker specs: tick_value, contract_size).

      Asset class detection via symbol keywords. FAIL thresholds:
        FX    : < $0.15  (empirically calibrated from burn-in evidence)
        XAU   : < $0.50  (3.3x FX: spread $0.20/oz vs FX $0.06/pip at 0.01 lot)
        BTC   : < $0.50  (3.3x FX: spread $20 vs FX, same cost at 0.01 lot)
        INDEX : < $0.50  (3.0-3.8x FX: GER40/NAS100/US30 spread vs FX)

      WATCH : above FAIL but below BURN_IN threshold
      BURN_IN candidates must have expectancy >= class threshold (enforced at promotion):
        FX $0.25 | XAU $0.80 | BTC $0.80 | INDEX $0.80

    BURN_IN is fully automated — driven by portfolio.yaml inclusion/exclusion.
    Adding a strategy to portfolio.yaml sets BURN_IN; removing it reverts to computed status.
    """
    total_trades = pd.to_numeric(df.get("total_trades"), errors="coerce").fillna(0.0)
    max_dd_pct = pd.to_numeric(df.get("max_dd_pct"), errors="coerce").fillna(float("inf"))
    return_dd_ratio = pd.to_numeric(df.get("return_dd_ratio"), errors="coerce").fillna(float("-inf"))
    sharpe_ratio = pd.to_numeric(df.get("sharpe_ratio"), errors="coerce").fillna(float("-inf"))
    sqn = pd.to_numeric(df.get("sqn"), errors="coerce").fillna(0.0)

    profit_factor = pd.to_numeric(df.get("profit_factor"), errors="coerce").fillna(float("-inf"))
    trade_density = pd.to_numeric(df.get("trade_density"), errors="coerce").fillna(0.0)
    expectancy = pd.to_numeric(df.get("expectancy"), errors="coerce").fillna(0.0)

    # --- Asset class detection from symbol column ---
    # Single source of truth: config.asset_classification.classify_asset()
    # Uses token-position-aware parsing, not substring matching.
    from config.asset_classification import classify_asset, EXP_FAIL_GATES

    symbol_col = df.get("symbol", pd.Series("", index=df.index)).fillna("").astype(str)
    asset_classes = symbol_col.apply(lambda s: classify_asset(s))
    is_fx    = (asset_classes == "FX")
    is_xau   = (asset_classes == "XAU")
    is_btc   = (asset_classes == "BTC")
    is_index = (asset_classes == "INDEX")

    status = pd.Series("WATCH", index=df.index, dtype="object")
    fail_mask = (total_trades < 50) | (max_dd_pct > 40)

    # Asset-class expectancy gates (from shared EXP_FAIL_GATES)
    fx_exp_fail  = is_fx    & (expectancy < EXP_FAIL_GATES["FX"])
    xau_exp_fail = is_xau   & (expectancy < EXP_FAIL_GATES["XAU"])
    btc_exp_fail = is_btc   & (expectancy < EXP_FAIL_GATES["BTC"])
    idx_exp_fail = is_index & (expectancy < EXP_FAIL_GATES["INDEX"])
    fail_mask = fail_mask | fx_exp_fail | xau_exp_fail | btc_exp_fail | idx_exp_fail
    fail_mask = fail_mask | (sqn < 1.5)

    core_mask = (
        (total_trades >= 200)
        & (return_dd_ratio >= 2.0)
        & (sharpe_ratio >= 1.5)
        & (sqn >= 2.5)
        & (max_dd_pct <= 30.0)
        & (trade_density >= 50.0)
        & (profit_factor >= 1.25)
        & (~fail_mask)
    )
    status.loc[fail_mask] = "FAIL"
    status.loc[core_mask] = "CORE"

    # Auto-set BURN_IN from portfolio.yaml — overrides computed status.
    # Matches by exact ID or prefix (portfolio ID + "_SYMBOL" pattern in xlsx).
    burnin_ids = _load_burnin_ids()
    if burnin_ids and "strategy" in df.columns:
        def _is_burnin(strat_name: str) -> bool:
            s = str(strat_name)
            if s in burnin_ids:
                return True
            return any(s.startswith(bid + "_") for bid in burnin_ids)

        burnin_mask = df["strategy"].apply(_is_burnin)
        if burnin_mask.any():
            status.loc[burnin_mask] = "BURN_IN"
            print(f"[CANDIDATES] BURN_IN auto-set for {burnin_mask.sum()} row(s) from portfolio.yaml")

    return status


def _apply_candidate_status(df: pd.DataFrame) -> pd.DataFrame:
    """Add/update candidate_status and IN_PORTFOLIO, keep them adjacent."""
    out = df.copy()
    out["candidate_status"] = _compute_candidate_status(out)

    # Sync IN_PORTFOLIO with BURN_IN status:
    #   BURN_IN → True  (strategy is in portfolio.yaml)
    #   removed from BURN_IN → False  (strategy no longer in portfolio.yaml)
    if "IN_PORTFOLIO" in out.columns:
        burnin = out["candidate_status"] == "BURN_IN"
        was_true = out["IN_PORTFOLIO"].astype(str).str.strip().str.lower() == "true"
        newly_true = burnin & ~was_true
        newly_false = ~burnin & was_true
        out.loc[burnin, "IN_PORTFOLIO"] = True
        out.loc[~burnin & was_true, "IN_PORTFOLIO"] = False
        if newly_true.any():
            print(f"[CANDIDATES] IN_PORTFOLIO set True for {newly_true.sum()} BURN_IN row(s)")
        if newly_false.any():
            print(f"[CANDIDATES] IN_PORTFOLIO set False for {newly_false.sum()} row(s) removed from BURN_IN")

    cols = out.columns.tolist()
    if "candidate_status" in cols:
        cols.remove("candidate_status")
    if "IN_PORTFOLIO" in cols:
        idx = cols.index("IN_PORTFOLIO") + 1
    else:
        idx = len(cols)
    cols = cols[:idx] + ["candidate_status"] + cols[idx:]
    return out[cols]


def filter_strategies():
    if not os.path.exists(MASTER_SHEET):
        print(f"ABORT: Error: {MASTER_SHEET} not found.")
        sys.exit(1)

    try:
        df = pd.read_excel(MASTER_SHEET)
    except Exception as e:
        print(f"ABORT: Error reading {MASTER_SHEET}: {e}")
        sys.exit(1)

    # Required metrics for promotion
    required_cols = [
        'profit_factor', 
        'return_dd_ratio', 
        'expectancy', 
        'total_trades', 
        'sharpe_ratio', 
        'max_dd_pct',
        'run_id',
        'strategy'
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        print(f"ABORT: Missing required columns in master sheet: {missing_cols}")
        print("Ensure Stage-3 compilation includes max_dd_pct.")
        sys.exit(1)

    nan_mask = df[required_cols].isna().any(axis=1)
    if nan_mask.any():
        affected_runs = df.loc[nan_mask, 'run_id'].tolist()
        print(f"ABORT: NaN detected in required metrics for run_ids: {affected_runs}")
        sys.exit(1)

    total_eval_runs = len(df)
    
    # Relaxed Criteria (User Proposed)
    # max_dd_pct is stored as a POSITIVE percentage (0..100) in the Master Filter.
    # E.g. 3.18 means 3.18% drawdown.  Threshold: exclude strategies with DD > 80%.
    _dd_col = pd.to_numeric(df['max_dd_pct'], errors='coerce').fillna(0.0)
    assert (_dd_col >= 0).all(), (
        f"SIGN_GUARD: max_dd_pct contains negative values — expected positive 0..100 scale"
    )
    mask = (
        (df['total_trades'] >= 40) &
        (df['profit_factor'] >= 1.05) &
        (df['return_dd_ratio'] >= 0.6) &
        (df['expectancy'] >= 0.0) &
        (df['sharpe_ratio'] >= 0.3) &
        (_dd_col <= 80.0)
    )

    passed_df = df[mask].copy()
    
    # --- CANDIDATE LEDGER GENERATION ---
    # Append+dedup semantics: previously passing strategies are never evicted,
    # even if they are temporarily absent from the Master Filter (e.g., during
    # re-run cleanup cycles where old rows are removed before re-running).
    if not passed_df.empty or CANDIDATE_FILTER_PATH.exists():
        try:
            # Step 1: Archive existing candidates file before any mutation.
            if CANDIDATE_FILTER_PATH.exists():
                archive_dir = CANDIDATE_FILTER_PATH.parent / "archive"
                archive_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                shutil.copy2(
                    CANDIDATE_FILTER_PATH,
                    archive_dir / f"Filtered_Strategies_Passed_{ts}.xlsx",
                )
                print(f"[CANDIDATES] Archived previous candidates to {archive_dir.name}/Filtered_Strategies_Passed_{ts}.xlsx")

            # Step 2: Read-modify-write with dedup on run_id.
            # Existing rows whose run_id appears in the current Master Filter
            # have their metric columns refreshed (handles re-runs and corrections).
            # Rows NOT in the current Master Filter are preserved as-is (append-only).
            if CANDIDATE_FILTER_PATH.exists():
                try:
                    df_existing = pd.read_excel(CANDIDATE_FILTER_PATH)
                    existing_run_ids = (
                        set(df_existing["run_id"].astype(str).tolist())
                        if "run_id" in df_existing.columns
                        else set()
                    )
                    # Identify new rows (not yet in candidates)
                    df_new_rows = passed_df[~passed_df["run_id"].astype(str).isin(existing_run_ids)]

                    # Refresh metrics for existing rows that are also in passed_df
                    # Preserve non-metric columns (IN_PORTFOLIO, burn_in_layer, etc.)
                    _preserve_cols = {"IN_PORTFOLIO", "burn_in_layer"}
                    refreshed_ids = set(passed_df["run_id"].astype(str)) & existing_run_ids
                    if refreshed_ids:
                        passed_lookup = passed_df.set_index(passed_df["run_id"].astype(str))
                        metric_cols = [c for c in passed_df.columns if c not in _preserve_cols]
                        for idx_row in df_existing.index:
                            rid = str(df_existing.at[idx_row, "run_id"])
                            if rid in refreshed_ids and rid in passed_lookup.index:
                                src = passed_lookup.loc[rid]
                                if isinstance(src, pd.DataFrame):
                                    src = src.iloc[0]
                                for col in metric_cols:
                                    if col in df_existing.columns:
                                        df_existing.at[idx_row, col] = src[col]
                        print(f"[CANDIDATES] Refreshed metrics for {len(refreshed_ids)} existing row(s) from Master Filter")

                    df_merged = pd.concat([df_existing, df_new_rows], ignore_index=True)
                    print(f"[CANDIDATES] Merged: {len(existing_run_ids)} existing + {len(df_new_rows)} new = {len(df_merged)} total")
                except Exception as read_err:
                    print(f"[WARN] Could not read existing candidates file ({read_err}) — writing fresh.")
                    df_merged = passed_df
            else:
                df_merged = passed_df

            # Preserve manually-set RBIN (Removed from Burn-In) status — these rows
            # were flagged by human review and should not revert to computed status.
            _rbin_ids = set()
            if "candidate_status" in df_merged.columns:
                _rbin_mask = df_merged["candidate_status"] == "RBIN"
                if _rbin_mask.any() and "run_id" in df_merged.columns:
                    _rbin_ids = set(df_merged.loc[_rbin_mask, "run_id"].astype(str))

            # Deterministic classification-only field; no filtering side effects.
            df_merged = _apply_candidate_status(df_merged)

            # Restore RBIN where it was set before recomputation.
            if _rbin_ids and "run_id" in df_merged.columns:
                restore_mask = df_merged["run_id"].astype(str).isin(_rbin_ids)
                df_merged.loc[restore_mask, "candidate_status"] = "RBIN"
                print(f"[CANDIDATES] Preserved RBIN status for {restore_mask.sum()} row(s)")

            # Compute asset_class column for easy Excel filtering (FX, XAU, INDEX, BTC, etc.)
            if "symbol" in df_merged.columns:
                from config.asset_classification import classify_asset
                df_merged["asset_class"] = df_merged["symbol"].fillna("").astype(str).apply(classify_asset)
                # Insert immediately after 'symbol' column
                cols = df_merged.columns.tolist()
                cols.remove("asset_class")
                sym_idx = cols.index("symbol") + 1
                cols.insert(sym_idx, "asset_class")
                df_merged = df_merged[cols]

            # Compute base_strategy_id: strip trailing _SYMBOL suffix.
            # Used by add_strategy_hyperlinks.py to build clickable links.
            if "strategy" in df_merged.columns and "symbol" in df_merged.columns:
                def _derive_base_id(row):
                    strat = str(row.get("strategy", ""))
                    sym = str(row.get("symbol", ""))
                    suffix = f"_{sym}"
                    if sym and strat.endswith(suffix):
                        return strat[: -len(suffix)]
                    print(f"[WARN] strategy '{strat}' does not end with '_{sym}' — base_strategy_id set to None")
                    return None

                df_merged["base_strategy_id"] = df_merged.apply(_derive_base_id, axis=1)
                # Insert immediately after 'strategy' column
                cols = df_merged.columns.tolist()
                cols.remove("base_strategy_id")
                strat_idx = cols.index("strategy") + 1
                cols.insert(strat_idx, "base_strategy_id")
                df_merged = df_merged[cols]

            # Preserve non-data sheets (e.g. Notes) during rewrite
            _preserved = {}
            if CANDIDATE_FILTER_PATH.exists():
                try:
                    _wb_old = openpyxl.load_workbook(CANDIDATE_FILTER_PATH, read_only=True)
                    for _sn in _wb_old.sheetnames:
                        if _sn != "Sheet1":
                            _preserved[_sn] = pd.read_excel(CANDIDATE_FILTER_PATH, sheet_name=_sn)
                    _wb_old.close()
                except Exception:
                    pass

            with pd.ExcelWriter(CANDIDATE_FILTER_PATH, engine="openpyxl", mode="w") as writer:
                df_merged.to_excel(writer, sheet_name="Sheet1", index=False)
                for _sn, _sdf in _preserved.items():
                    _sdf.to_excel(writer, sheet_name=_sn, index=False)

            print(f"[SUCCESS] Candidate ledger written: {CANDIDATE_FILTER_PATH}")

            # Step 3: Format the merged ledger.
            import subprocess
            formatter_path = PROJECT_ROOT / "tools" / "format_excel_artifact.py"
            try:
                subprocess.run(
                    [sys.executable, str(formatter_path), "--file", str(CANDIDATE_FILTER_PATH), "--profile", "strategy"],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"[WARN] Failed to format candidate ledger: {e.stderr.decode()}")

            try:
                subprocess.run(
                    [sys.executable, str(formatter_path), "--file", str(CANDIDATE_FILTER_PATH), "--notes-type", "candidates"],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"[WARN] Failed to add Notes sheet to candidate ledger: {e.stderr.decode()}")

        except Exception as e:
            print(f"[ERROR] Failed to generate candidate ledger: {e}")
    # -----------------------------------

    if passed_df.empty:
        print("Total evaluated:", total_eval_runs)
        print("Passed this run: 0")
        return

    # 1. Load Registry
    reg = _load_registry()
    promoted_count = 0
    migration_count = 0

    # 2. Process Passing Strategies
    for _, row in passed_df.iterrows():
        run_id = str(row['run_id'])
        strat_name = str(row['strategy'])
        
        if run_id not in reg:
            continue
            
        current_tier = reg[run_id].get("tier", "sandbox")
        if current_tier == "candidate":
            continue
            
        # 1. Update Registry Tier (Authoritative)
        reg[run_id]["tier"] = "sandbox"
        _save_registry_atomic(reg) # Persist immediately
        promoted_count += 1
        
        # 2. Physical Migration
        src_path = RUNS_DIR / run_id
        dest_path = POOL_DIR / run_id

        if src_path.exists() and not dest_path.exists():
            try:
                POOL_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_path), str(dest_path))
                migration_count += 1
                print(f"[MIGRATED] {run_id} -> sandbox/")
            except Exception as e:
                print(f"[ERROR] Physical migration failed for {run_id}: {e}")
                # Note: We do NOT revert the tier. The registry is authoritative.
                # Reconcile or a future run will fix the physical location.

    # Final Output Summary
    print("Total evaluated:", total_eval_runs)
    print("Passed criteria:", len(passed_df))
    print("Newly promoted to candidate:", promoted_count)
    print("Physically migrated:", migration_count)

if __name__ == "__main__":
    filter_strategies()
