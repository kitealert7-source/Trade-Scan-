"""
Canonical artifact loader.
Reads CSVs once, parses timestamps once, validates schemas.
"""
import json
from pathlib import Path
import pandas as pd

from tools.robustness.schema import validate_trade_df, validate_equity_df

def load_canonical_artifacts(prefix: str, profile: str, project_root: Path):
    deploy_dir = project_root / "strategies" / prefix / "deployable" / profile
    if not deploy_dir.exists():
        raise FileNotFoundError(f"Deployable artifacts directory not found: {deploy_dir}")

    # Load trades
    tr_df = pd.read_csv(deploy_dir / "deployable_trade_log.csv")
    validate_trade_df(tr_df)
    
    # Parse timestamps computationally once
    tr_df["entry_timestamp"] = pd.to_datetime(tr_df["entry_timestamp"])
    tr_df["exit_timestamp"] = pd.to_datetime(tr_df["exit_timestamp"])

    # Load equity
    eq_df = pd.read_csv(deploy_dir / "equity_curve.csv")
    validate_equity_df(eq_df)
    
    # Parse timestamps computationally once
    eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])

    # Load metrics
    with open(deploy_dir / "summary_metrics.json", "r") as f:
        metrics = json.load(f)

    # Canonical deterministic ordering
    tr_df = tr_df.sort_values("exit_timestamp").reset_index(drop=True)
    eq_df = eq_df.sort_values("timestamp").reset_index(drop=True)

    return tr_df, eq_df, metrics
