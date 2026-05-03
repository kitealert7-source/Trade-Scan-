"""
Canonical artifact loader.
Reads CSVs once, parses timestamps once, validates schemas.
"""
import json
from pathlib import Path
from config.state_paths import RUNS_DIR, BACKTESTS_DIR, STRATEGIES_DIR, SELECTED_DIR
import pandas as pd

from tools.robustness.schema import validate_trade_df, validate_equity_df

def load_canonical_artifacts(prefix: str, profile: str, project_root: Path):
    deploy_dir = STRATEGIES_DIR / prefix / "deployable" / profile
    if not deploy_dir.exists():
        raise FileNotFoundError(f"Deployable artifacts directory not found: {deploy_dir}")

    # Load trades
    tr_df = pd.read_csv(deploy_dir / "deployable_trade_log.csv")
    validate_trade_df(tr_df)

    # Partial-aware totalization: if partial legs are present, pnl_usd in the raw
    # log carries ONLY the final leg. Merge partial_pnl_usd in so every downstream
    # consumer (MC, tail, bootstrap, temporal, symbol) sees the full trade PnL.
    # When the column is absent (pre-v1.5.7 runs), this is a no-op.
    if "partial_pnl_usd" in tr_df.columns:
        tr_df["pnl_usd"] = tr_df["pnl_usd"].fillna(0) + tr_df["partial_pnl_usd"].fillna(0)

    # Parse timestamps computationally once
    tr_df["entry_timestamp"] = pd.to_datetime(tr_df["entry_timestamp"])
    tr_df["exit_timestamp"] = pd.to_datetime(tr_df["exit_timestamp"])

    # Load equity
    eq_df = pd.read_csv(deploy_dir / "equity_curve.csv")
    validate_equity_df(eq_df)
    
    # Parse timestamps computationally once
    eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])

    # Load metrics
    with open(deploy_dir / "summary_metrics.json", "r", encoding="utf-8") as f:
        metrics = json.load(f)

    # Canonical deterministic ordering
    tr_df = tr_df.sort_values("exit_timestamp").reset_index(drop=True)
    eq_df = eq_df.sort_values("timestamp").reset_index(drop=True)

    # Load all profiles from profile_comparison.json (written by post_process_capital.py)
    # Located at deployable/ (parent of profile subdir)
    # Returns full profiles dict so runner can access current profile + RAW_MIN_LOT_V1 baseline
    all_profiles = {}
    comp_path = deploy_dir.parent / "profile_comparison.json"
    if comp_path.exists():
        try:
            with open(comp_path, "r", encoding="utf-8") as f:
                _comp = json.load(f)
            all_profiles = _comp.get("profiles", {})
        except Exception:
            pass

    return tr_df, eq_df, metrics, all_profiles
