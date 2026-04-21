"""Data loading: trade artifacts + per-symbol Stage-3 metrics."""

from __future__ import annotations

import json

import pandas as pd

from tools.portfolio.portfolio_config import BACKTESTS_ROOT, PROJECT_ROOT
from tools.portfolio_core import (
    load_trades_for_portfolio_evaluator as core_load_trades_for_portfolio_evaluator,
)


def load_all_trades(run_ids):
    """
    Load trade-level results for explicit atomic runs.
    Bypasses auto-discovery and Excel UI parsing.
    Sourced purely from runs/<run_id>/data/ results.
    """
    return core_load_trades_for_portfolio_evaluator(run_ids, PROJECT_ROOT)


def load_symbol_metrics(strategy_id):
    """
    Load per-symbol standard and risk metrics (Governance-Driven).
    Replaces auto-discovery with strict Stage-3 Master Filter selection.
    Uses Run-ID based folder resolution (no folder filtering).
    """
    metrics = {}

    # 1. Read Master Sheet (DB-first, Excel fallback)
    try:
        from tools.ledger_db import read_master_filter
        df_master = read_master_filter()
        if df_master.empty:
            raise ValueError("Master Filter is empty")
    except Exception as e:
        raise ValueError(f"Failed to read Strategy Master Filter: {e}")

    # 2. Filter Rows.
    # IN_PORTFOLIO was retired 2026-04-16 and is no longer required; the
    # filter below matches by strategy prefix, which is the authoritative
    # semantics for resolving per-symbol run rows.
    if 'strategy' not in df_master.columns or 'run_id' not in df_master.columns or 'symbol' not in df_master.columns:
         raise ValueError("Master Sheet missing required columns: 'strategy', 'run_id', or 'symbol'")

    selected_rows = df_master[
        (df_master['strategy'].astype(str).str.startswith(strategy_id + "_"))
    ]

    if selected_rows.empty:
        # Fallback: Try Exact Match
        selected_rows = df_master[df_master['strategy'] == strategy_id]

    if selected_rows.empty:
        raise ValueError(f"No strategies found in Master Filter matching {strategy_id}")

    # 3. Locate Folders (Pre-scan for Run-ID mapping)
    run_id_map = {}
    for folder in BACKTESTS_ROOT.iterdir():
        if folder.is_dir():
            meta_path = folder / "metadata" / "run_metadata.json"
            if meta_path.exists():
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                except Exception:
                    continue

                rid = str(meta.get("run_id"))

                # Governance: Detect duplicates strict
                if rid in run_id_map:
                    raise ValueError(f"Duplicate run_id detected in backtests: {rid}")

                run_id_map[rid] = folder

    # 4. Load Metrics
    for idx, row in selected_rows.iterrows():
        run_id = str(row['run_id'])
        symbol = row.get('symbol')

        run_folder = run_id_map.get(run_id)
        if run_folder is None:
             raise ValueError(
                f"Governance violation: run_id {run_id} selected in Master Sheet "
                f"but no corresponding backtest folder found."
            )

        std_path = run_folder / "raw" / "results_standard.csv"
        risk_path = run_folder / "raw" / "results_risk.csv"

        if not std_path.exists() or not risk_path.exists():
            raise ValueError(
                f"Governance violation: standard/risk metrics missing for run_id {run_id}."
            )

        try:
            std = pd.read_csv(std_path).iloc[0].to_dict()
            risk = pd.read_csv(risk_path).iloc[0].to_dict()
            if symbol:
                metrics[symbol] = {**std, **risk}
        except Exception as e:
            raise ValueError(
                f"Governance violation: failed to read metrics for run_id {run_id}: {e}"
            )

    return metrics
