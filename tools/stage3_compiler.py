"""
Stage-3 Aggregation Engine — Strategy Master Filter Population
Governed by: SOP_OUTPUT §6

This engine is READ-ONLY (for inputs), COPY-ONLY, and APPEND-ONLY (for Master Sheet).
No computation, derivation, inference, or ranking is performed.
Values are treated as opaque scalars — no conversion or cleaning.
Rewritten to use pandas and Unified Formatter (Zero OpenPyXL Styling / Imports).

Authority: SOP_OUTPUT
State Gated: Yes (STAGE_3_START)
"""

import json
import sys
import subprocess
from pathlib import Path
import pandas as pd
from datetime import datetime

# Config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Governance Imports
from tools.pipeline_utils import PipelineStateManager
from config.state_paths import POOL_DIR, BACKTESTS_DIR, RUNS_DIR

BACKTESTS_ROOT = BACKTESTS_DIR

# Column schema per SOP_OUTPUT §6 (exact order)
MASTER_FILTER_COLUMNS = [
    "run_id",
    "strategy",
    "symbol",
    "timeframe",
    "test_start",
    "test_end",
    "trading_period",
    "total_trades",
    "trade_density",
    "total_net_profit",
    "gross_profit",
    "gross_loss",
    "profit_factor",
    "expectancy",
    "sharpe_ratio",
    "max_drawdown",
    "max_dd_pct",
    "return_dd_ratio",
    "worst_5_loss_pct",
    "longest_loss_streak",
    "pct_time_in_market",
    "avg_bars_in_trade",
    "net_profit_high_vol",
    "net_profit_normal_vol",
    "net_profit_low_vol",
    "net_profit_asia",
    "net_profit_london",
    "net_profit_ny",
    # Trend Breakdown (SOP v4.2)
    "net_profit_strong_up",
    "net_profit_weak_up",
    "net_profit_neutral",
    "net_profit_weak_down",
    "net_profit_strong_down",
    "trades_strong_up",
    "trades_weak_up",
    "trades_neutral",
    "trades_weak_down",
    "trades_strong_down",
    "IN_PORTFOLIO",
]

# Required Performance Summary metric labels (EXACT, no fuzzy matching)
REQUIRED_METRICS = {
    "trading_period": "Trading Period (Days)",
    "total_trades": "Total Trades",
    "total_net_profit": "Net Profit (USD)",
    "gross_profit": "Gross Profit (USD)",
    "gross_loss": "Gross Loss (USD)",
    "profit_factor": "Profit Factor",
    "expectancy": "Expectancy (USD)",
    "sharpe_ratio": "Sharpe Ratio",
    "max_drawdown": "Max Drawdown (USD)",
    "max_dd_pct": "Max Drawdown (%)",
    "return_dd_ratio": "Return / Drawdown Ratio",
    "worst_5_loss_pct": "Worst 5 Trades Loss %",
    "longest_loss_streak": "Max Consecutive Losses",
    "pct_time_in_market": "% Time in Market",
    "avg_bars_in_trade": "Avg Bars per Trade",
}

# Volatility metric labels (EXACT)
VOLATILITY_METRICS = {
    "net_profit_high_vol": "Net Profit - High Volatility",
    "net_profit_normal_vol": "Net Profit - Normal Volatility",
    "net_profit_low_vol": "Net Profit - Low Volatility",
    "net_profit_asia": "Net Profit - Asia Session",
    "net_profit_london": "Net Profit - London Session",
    "net_profit_ny": "Net Profit - New York Session",
}

# Trend regime metric labels (EXACT) — optional; populated by Stage 2 for new runs only
TREND_METRICS = {
    "net_profit_strong_up":   "Net Profit - Strong Up",
    "net_profit_weak_up":     "Net Profit - Weak Up",
    "net_profit_neutral":     "Net Profit - Neutral",
    "net_profit_weak_down":   "Net Profit - Weak Down",
    "net_profit_strong_down": "Net Profit - Strong Down",
    "trades_strong_up":       "Trades - Strong Up",
    "trades_weak_up":         "Trades - Weak Up",
    "trades_neutral":         "Trades - Neutral",
    "trades_weak_down":       "Trades - Weak Down",
    "trades_strong_down":     "Trades - Strong Down",
}
TRADE_DENSITY_LABEL = "Trade Density (Trades/Year)"

# ── Report schema constants (single source of truth for Excel layout) ──────────
_REPORT_SHEET       = "Performance Summary"
_REPORT_METRIC_COL  = "Metric"
_REPORT_VALUE_COL   = "All Trades"
_DAILY_NAN_MARKER   = "Daily_Nan"
_DAILY_SESSION_COLS = frozenset({"net_profit_asia", "net_profit_london", "net_profit_ny"})

# Optional metrics: present in new runs, absent in old. Extraction never hard-fails.
# TRADE_DENSITY_LABEL kept as standalone export for stage_schema_validation import compat.
OPTIONAL_METRICS: dict = {
    "trade_density": TRADE_DENSITY_LABEL,
}

# ── Reverse mapping: Excel label → canonical key (built once at load time) ──────
# Used by extract_performance_metrics() to remap the label-keyed Excel dict to
# canonical keys so all downstream extraction operates on col_name, not label string.
_LABEL_TO_CANONICAL: dict = {
    label: key
    for d in (REQUIRED_METRICS, VOLATILITY_METRICS, TREND_METRICS, OPTIONAL_METRICS)
    for key, label in d.items()
}

# Required metadata fields
REQUIRED_METADATA_FIELDS = [
    "run_id",
    "strategy_name",
    "symbol",
    "timeframe",
]

def load_run_metadata(run_folder):
    metadata_path = run_folder / "metadata" / "run_metadata.json"
    if not metadata_path.exists():
        return None
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_metadata(metadata, run_folder):
    if not metadata: return False, "run_metadata.json not found or empty"
    run_id = metadata.get("run_id")
    if not run_id: return False, "run_id is missing or empty"
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata or metadata[field] is None:
            return False, f"Missing required metadata field: {field}"
    date_range = metadata.get("date_range", {})
    if not date_range.get("start") or not date_range.get("end"):
        return False, "Missing date_range start/end"
    return True, None

def find_ak_trade_report(run_folder):
    matches = list(run_folder.glob("AK_Trade_Report_*.xlsx"))
    matches = [m for m in matches if not m.name.startswith("~$")]
    return matches[0] if matches else None

def extract_performance_metrics(report_path):
    """Extract metrics from AK_Trade_Report using pandas."""
    try:
        # Stage 2 generates _REPORT_SHEET with columns: _REPORT_METRIC_COL, _REPORT_VALUE_COL, ...
        df = pd.read_excel(report_path, sheet_name=_REPORT_SHEET)

        # Load label-keyed dict, then remap to canonical keys immediately.
        # Downstream code operates on canonical keys only — no label strings at runtime.
        if _REPORT_METRIC_COL in df.columns and _REPORT_VALUE_COL in df.columns:
            df[_REPORT_METRIC_COL] = df[_REPORT_METRIC_COL].astype(str).str.strip()
            label_metrics = df.set_index(_REPORT_METRIC_COL)[_REPORT_VALUE_COL].to_dict()
            return {_LABEL_TO_CANONICAL.get(lbl, lbl): val for lbl, val in label_metrics.items()}
        return {}
    except Exception as e:
        print(f"[WARN] Failed to read metrics from {report_path.name}: {e}")
        return {}

def validate_required_metrics(metrics, run_id):
    # All three groups are REQUIRED. No optional metrics in the aggregation layer.
    # Old runs missing trend metrics must be regenerated via: python -m tools.rebuild_all_reports
    # metrics is canonical-keyed; check by canonical col_name, not label string.
    missing = [col for col in REQUIRED_METRICS if col not in metrics]
    missing += [col for col in VOLATILITY_METRICS if col not in metrics]
    missing += [col for col in TREND_METRICS if col not in metrics]
    return (False, missing) if missing else (True, [])

def extract_from_report(report_path, metadata):
    metrics = extract_performance_metrics(report_path)
    run_id = metadata.get("run_id", "UNKNOWN")

    is_valid, missing = validate_required_metrics(metrics, run_id)
    if not is_valid:
        return None, f"Missing required metrics: {', '.join(missing)}"

    row_data = {
        "run_id": metadata.get("run_id"),
        "strategy": metadata.get("strategy_name"),
        "symbol": metadata.get("symbol"),
        "timeframe": metadata.get("timeframe"),
        "test_start": metadata.get("date_range", {}).get("start"),
        "test_end": metadata.get("date_range", {}).get("end"),
        "IN_PORTFOLIO": False,
    }

    # All lookups use canonical col_name — no label strings at runtime.
    for col_name in REQUIRED_METRICS:
        row_data[col_name] = metrics.get(col_name)

    for col_name in OPTIONAL_METRICS:
        if col_name in metrics:
            val = metrics[col_name]
            row_data[col_name] = int(val) if pd.notnull(val) else 0
        elif col_name == "trade_density":
            # BACKWARD COMPAT ONLY — DO NOT USE FOR NEW RUNS
            # Old AK_Trade_Reports (pre-schema-update) do not carry Trade Density.
            # Derive from total_trades and trading_period already extracted above.
            try:
                tt = float(row_data.get("total_trades") or 0)
                tp = float(row_data.get("trading_period") or 365.25)
                row_data[col_name] = int(round(tt / (tp / 365.25))) if tp > 0 else 0
            except (ValueError, TypeError):
                row_data[col_name] = 0

    for col_name in VOLATILITY_METRICS:
        row_data[col_name] = metrics.get(col_name)

    # Daily bars do not have meaningful session attribution.
    timeframe = str(metadata.get("timeframe", "")).strip().lower()
    if timeframe in {"1d", "d", "daily"}:
        for col in _DAILY_SESSION_COLS:
            row_data[col] = _DAILY_NAN_MARKER

    # Trend metrics: REQUIRED. validate_required_metrics() guarantees all keys present above.
    for col_name in TREND_METRICS:
        row_data[col_name] = metrics[col_name]

    return row_data, None

def get_existing_master_df(master_filter_path):
    if not master_filter_path.exists():
        return pd.DataFrame(columns=MASTER_FILTER_COLUMNS)
    try:
        return pd.read_excel(master_filter_path)
    except Exception:
        return pd.DataFrame(columns=MASTER_FILTER_COLUMNS)

def enforce_strategy_persistence(run_id: str):
    strategy_dir = RUNS_DIR / run_id
    if not strategy_dir.exists():
        print(f"  [WARN] Strategy persistence check failed: runs/{run_id} missing. Proceeding (Legacy Run).")
        return
        # raise RuntimeError(f"Strategy folder missing: runs/{run_id}")
    allowed = {"strategy.py", "__pycache__", "run_state.json", "run_state.json.tmp"} # Added accepted state files
    found = {p.name for p in strategy_dir.iterdir()}
    if "strategy.py" not in found:
        print(f"  [WARN] strategy.py missing in runs/{run_id}. Proceeding (Legacy Run).")
        return
        # raise RuntimeError(f"strategy.py missing in runs/{run_id}")
    extra = found - allowed
    if extra:
        print(f"  [WARN] Non-compliant files in runs/{run_id}: {sorted(extra)}")
        # raise RuntimeError(f"Non-compliant files in runs/{run_id}: {sorted(extra)}")

def discover_completed_runs():
    runs = []
    rejected = []
    for run_folder in BACKTESTS_ROOT.iterdir():
        if not run_folder.is_dir() or run_folder.name.startswith("."): continue
        metadata = load_run_metadata(run_folder)
        is_valid, error = validate_metadata(metadata, run_folder)
        if not is_valid:
            rejected.append({"folder": run_folder.name, "reason": error})
            continue
        report_path = find_ak_trade_report(run_folder)
        if not report_path:
            rejected.append({"folder": run_folder.name, "reason": "AK_Trade_Report not found"})
            continue
        runs.append({"folder": run_folder, "metadata": metadata, "report_path": report_path})
    return runs, rejected

def compile_stage3(strategy_filter=None):
    print("Stage-3 Aggregation Engine (Clean Batch)")
    print("=" * 60)
    
    runs, discovery_rejected = discover_completed_runs()
    if strategy_filter:
        runs = [r for r in runs if r["metadata"].get("strategy_name", "").startswith(strategy_filter)]
    
    print(f"Discovered {len(runs)} valid runs")
    if discovery_rejected:
        print(f"Rejected at discovery: {len(discovery_rejected)}")
    
    master_filter_path = POOL_DIR / "Strategy_Master_Filter.xlsx"
    df_master = get_existing_master_df(master_filter_path)
    
    # Ensure IN_PORTFOLIO exists
    if "IN_PORTFOLIO" not in df_master.columns:
        print("[MIGRATION] Adding IN_PORTFOLIO column")
        df_master["IN_PORTFOLIO"] = False
    
    existing_ids = set(df_master["run_id"].astype(str).tolist()) if "run_id" in df_master.columns else set()
    print(f"Existing runs in Master Filter: {len(existing_ids)}")
    
    added = []
    skipped = []
    new_rows = []
    
    for run in runs:
        run_id = str(run["metadata"].get("run_id"))
        strategy = run["metadata"].get("strategy_name")
        
        # --- GOVERNANCE CHECK ---
        try:
             state_mgr = PipelineStateManager(run_id)
             state_mgr.verify_state("STAGE_2_COMPLETE")
        except Exception as e:
             msg = f"Governance Fail: {e}"
             skipped.append({"strategy": strategy, "run_id": run_id, "reason": msg})
             print(f"  SKIPPED: {strategy} [{run_id[:8]}] - {msg}")
             continue
        # ------------------------
        
        if run_id in existing_ids:
            skipped.append({"strategy": strategy, "run_id": run_id, "reason": "Already exists"})
            continue
        
        row_data, error = extract_from_report(run["report_path"], run["metadata"])
        if error:
            skipped.append({"strategy": strategy, "run_id": run_id, "reason": error})
            print(f"  REJECTED: {strategy} [{run_id[:8]}] - {error}")
            continue
        
        enforce_strategy_persistence(run_id)
        new_rows.append(row_data)
        added.append({"strategy": strategy, "run_id": run_id})
        print(f"  Added: {strategy} [{run_id[:8]}]")
    
    if new_rows:
        df_new = pd.DataFrame(new_rows)
        # Ensure col order
        for c in MASTER_FILTER_COLUMNS:
            if c not in df_new.columns: df_new[c] = None
        df_new = df_new[MASTER_FILTER_COLUMNS]
        
        df_master = pd.concat([df_master, df_new], ignore_index=True)
        
        # Save
        try:
            print(f"[DEBUG] df_master shape before save: {df_master.shape}")
            print(f"[DEBUG] df_new shape: {df_new.shape}")
            df_master.to_excel(master_filter_path, index=False)
            
            # Format
            project_root = Path(__file__).parent.parent
            formatter = project_root / "tools" / "format_excel_artifact.py"
            cmd = [sys.executable, str(formatter), "--file", str(master_filter_path), "--profile", "strategy"]
            subprocess.run(cmd, check=True)
            print("[SUCCESS] Master Filter updated and formatted.")
        except Exception as e:
            print(f"[FATAL] Failed to save Master Filter: {e}")
            sys.exit(1)
            
    else:
        print("No new runs to add.")

    print("\n" + "=" * 60)
    print("STAGE-3 SUMMARY")
    print("=" * 60)
    print(f"Rows added: {len(added)}")
    print(f"Rows skipped: {len(skipped)}")
    
    return {"added": added, "skipped": skipped, "output_path": str(master_filter_path)}

def main():
    import sys
    strategy_filter = sys.argv[1] if len(sys.argv) > 1 else None
    compile_stage3(strategy_filter)

if __name__ == "__main__":
    main()
