"""
generate_run_summary.py — Build a denormalized run summary view.

Joins run_registry.json (provenance) + index.csv (per-symbol metrics)
+ Master_Portfolio_Sheet.xlsx (portfolio verdict) into a single flat CSV:

    TradeScan_State/research/run_summary.csv

One row per run_id with aggregated metrics.  Queryable by any tool
(pandas, Excel, SQL, future dashboard layer).

Auto-called by run_pipeline.py after each PORTFOLIO_COMPLETE directive.
Also runnable standalone:

    python tools/generate_run_summary.py          # regenerate
    python tools/generate_run_summary.py --quiet   # silent (for pipeline use)

Idempotent: overwrites the summary on every run.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import (
    STATE_ROOT,
    REGISTRY_DIR,
    STRATEGIES_DIR,
    CANDIDATES_DIR,
)

REGISTRY_PATH  = REGISTRY_DIR / "run_registry.json"
INDEX_PATH     = STATE_ROOT / "research" / "index.csv"
PORTFOLIO_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"
CANDIDATE_PATH = CANDIDATES_DIR / "Filtered_Strategies_Passed.xlsx"
OUTPUT_PATH    = STATE_ROOT / "research" / "run_summary.csv"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def _load_registry() -> pd.DataFrame:
    """Load run_registry.json → DataFrame with run_id, tier, status, created_at, directive_hash."""
    if not REGISTRY_PATH.exists():
        return pd.DataFrame()
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    rows = list(data.values())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Rename directive_hash → strategy_id for join clarity
    if "directive_hash" in df.columns:
        df = df.rename(columns={"directive_hash": "strategy_id"})
    return df


def _load_index() -> pd.DataFrame:
    """Load index.csv — per-symbol backtest results."""
    if not INDEX_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(INDEX_PATH, dtype={"run_id": str})


def _load_portfolio_verdicts() -> pd.DataFrame:
    """Load Master_Portfolio_Sheet.xlsx — explode constituent_run_ids to per-run verdicts.

    The portfolio sheet has one row per *portfolio* with constituent_run_ids as a
    comma-separated list. We explode so each run_id gets the portfolio's verdict.
    """
    try:
        from tools.ledger_db import read_mps
        df = read_mps()  # all sheets
        if df.empty:
            return pd.DataFrame()
        df.columns = [c.strip().lower() for c in df.columns]

        if "constituent_run_ids" not in df.columns:
            return pd.DataFrame()

        # Extract verdict column
        verdict_col = None
        for candidate in ["portfolio_status", "verdict", "portfolio_verdict"]:
            if candidate in df.columns:
                verdict_col = candidate
                break

        rows = []
        for _, row in df.iterrows():
            # Skip rows with unresolved/blocked status — they must not
            # propagate into downstream aggregation.
            if verdict_col and str(row.get(verdict_col, "")).strip() == "PROFILE_UNRESOLVED":
                continue
            run_ids_str = str(row.get("constituent_run_ids", ""))
            if not run_ids_str or run_ids_str == "nan":
                continue
            verdict = str(row.get(verdict_col, "")) if verdict_col else ""
            risk = str(row.get("deployed_profile", "")) if "deployed_profile" in df.columns else ""
            portfolio_id = str(row.get("portfolio_id", ""))
            pf = row.get("profit_factor") if "profit_factor" in df.columns else None
            sharpe = row.get("sharpe") if "sharpe" in df.columns else None
            for rid in run_ids_str.split(","):
                rid = rid.strip()
                if rid:
                    rows.append({
                        "run_id": rid,
                        "portfolio_verdict": verdict,
                        "portfolio_id": portfolio_id,
                        "portfolio_pf": pf,
                        "portfolio_sharpe": sharpe,
                        "risk_profile": risk,
                    })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).drop_duplicates(subset=["run_id"])
    except Exception:
        return pd.DataFrame()


def _load_candidate_status() -> pd.DataFrame:
    """Load Filtered_Strategies_Passed.xlsx for candidate_status (CORE/WATCH/FAIL/BURN_IN)."""
    if not CANDIDATE_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_excel(CANDIDATE_PATH)
        df.columns = [c.strip().lower() for c in df.columns]
        cols_keep = []
        if "run_id" in df.columns:
            cols_keep.append("run_id")
        if "candidate_status" in df.columns:
            cols_keep.append("candidate_status")
        if "in_portfolio" in df.columns:
            cols_keep.append("in_portfolio")
        if not cols_keep or "run_id" not in cols_keep:
            return pd.DataFrame()
        return df[cols_keep].drop_duplicates(subset=["run_id"])
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _aggregate_index(df_index: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-symbol rows into per-run_id summary."""
    if df_index.empty:
        return pd.DataFrame()

    # Ensure numeric columns
    num_cols = ["profit_factor", "max_drawdown_pct", "net_pnl_usd", "total_trades", "win_rate"]
    for c in num_cols:
        if c in df_index.columns:
            df_index[c] = pd.to_numeric(df_index[c], errors="coerce")

    agg = df_index.groupby("run_id", as_index=False).agg(
        strategy_id=("strategy_id", "first"),
        symbols=("symbol", lambda x: ",".join(sorted(x.unique()))),
        symbol_count=("symbol", "nunique"),
        timeframe=("timeframe", "first"),
        date_start=("date_start", "min"),
        date_end=("date_end", "max"),
        total_trades=("total_trades", "sum"),
        net_pnl_usd=("net_pnl_usd", "sum"),
        avg_profit_factor=("profit_factor", "mean"),
        avg_win_rate=("win_rate", "mean"),
        max_drawdown_pct=("max_drawdown_pct", "max"),
        execution_timestamp=("execution_timestamp_utc", "max"),
    )

    # Round for readability
    for c in ["net_pnl_usd", "avg_profit_factor", "avg_win_rate", "max_drawdown_pct"]:
        if c in agg.columns:
            agg[c] = agg[c].round(4)

    return agg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def generate(quiet: bool = False) -> Path:
    """Build and write run_summary.csv. Returns the output path."""
    df_reg = _load_registry()
    df_idx = _load_index()
    df_port = _load_portfolio_verdicts()
    df_cand = _load_candidate_status()

    if not quiet:
        print(f"  Registry:   {len(df_reg)} entries")
        print(f"  Index:      {len(df_idx)} rows")
        print(f"  Portfolio:  {len(df_port)} verdicts")
        print(f"  Candidates: {len(df_cand)} statuses")

    # Aggregate index to per-run level
    df_agg = _aggregate_index(df_idx)

    if df_agg.empty and df_reg.empty:
        if not quiet:
            print("  No data to summarize.")
        return OUTPUT_PATH

    # Start with aggregated metrics (richest data)
    if not df_agg.empty:
        df = df_agg.copy()
    else:
        df = pd.DataFrame(columns=["run_id"])

    # Merge registry (provenance: tier, status, created_at)
    if not df_reg.empty:
        reg_cols = ["run_id", "tier", "status", "created_at"]
        reg_cols = [c for c in reg_cols if c in df_reg.columns]
        if "run_id" in reg_cols:
            df = df.merge(df_reg[reg_cols], on="run_id", how="outer", suffixes=("", "_reg"))
            # Fill strategy_id from registry for runs not in index
            if "strategy_id_reg" in df.columns:
                df["strategy_id"] = df["strategy_id"].fillna(df["strategy_id_reg"])
                df = df.drop(columns=["strategy_id_reg"], errors="ignore")
            elif "strategy_id" not in df.columns and "strategy_id" in df_reg.columns:
                df = df.merge(
                    df_reg[["run_id", "strategy_id"]],
                    on="run_id", how="left", suffixes=("", "_r2")
                )

    # Merge portfolio verdicts
    if not df_port.empty and "run_id" in df_port.columns:
        df = df.merge(df_port, on="run_id", how="left")

    # Merge candidate status
    if not df_cand.empty and "run_id" in df_cand.columns:
        df = df.merge(df_cand, on="run_id", how="left")

    # Order columns for readability
    priority_cols = [
        "run_id", "strategy_id", "status", "tier",
        "symbol_count", "symbols", "timeframe",
        "total_trades", "net_pnl_usd", "avg_profit_factor",
        "avg_win_rate", "max_drawdown_pct",
        "portfolio_verdict", "portfolio_id", "portfolio_pf", "portfolio_sharpe",
        "candidate_status", "in_portfolio", "risk_profile",
        "date_start", "date_end", "created_at", "execution_timestamp",
    ]
    existing = [c for c in priority_cols if c in df.columns]
    remaining = [c for c in df.columns if c not in existing]
    df = df[existing + remaining]

    # Sort: most recent first
    sort_col = "execution_timestamp" if "execution_timestamp" in df.columns else "created_at"
    if sort_col in df.columns:
        df = df.sort_values(sort_col, ascending=False, na_position="last")

    # Write
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    if not quiet:
        print(f"\n  run_summary.csv: {len(df)} rows, {len(df.columns)} columns")
        print(f"  Written to: {OUTPUT_PATH}")

        # Quick stats
        if "status" in df.columns:
            print(f"\n  By status: {df['status'].value_counts().to_dict()}")
        if "portfolio_verdict" in df.columns:
            verdicts = df["portfolio_verdict"].dropna()
            verdicts = verdicts[verdicts != ""]
            if len(verdicts):
                print(f"  By portfolio verdict: {verdicts.value_counts().to_dict()}")
        if "net_pnl_usd" in df.columns:
            profitable = (df["net_pnl_usd"].dropna() > 0).sum()
            total = df["net_pnl_usd"].dropna().shape[0]
            print(f"  Profitable runs: {profitable}/{total}")

    return OUTPUT_PATH


def main():
    parser = argparse.ArgumentParser(description="Generate run_summary.csv")
    parser.add_argument("--quiet", "-q", action="store_true")
    args = parser.parse_args()

    if not args.quiet:
        print("Generating run summary view...")
        print("=" * 40)

    generate(quiet=args.quiet)

    if not args.quiet:
        print("=" * 40)
        print("Done.")


if __name__ == "__main__":
    main()
