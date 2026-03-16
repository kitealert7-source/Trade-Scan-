"""Portfolio evaluation and post-processing stages."""

from __future__ import annotations

import csv as _csv
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from tools.orchestration.pipeline_errors import PipelineExecutionError
from tools.orchestration.transition_service import (
    transition_directive_state,
    transition_run_state,
)
from tools.pipeline_utils import PipelineStateManager
from config.state_paths import RUNS_DIR, BACKTESTS_DIR, STRATEGIES_DIR


def run_portfolio_and_post_stages(
    *,
    clean_id: str,
    p_conf: dict,
    run_ids: list[str],
    symbols: list[str],
    project_root: Path,
    python_exe: str,
    run_command,
) -> None:
    """Execute stage-4 gates + non-authoritative post steps."""
    from tools.system_registry import _load_registry
    
    print("[ORCHESTRATOR] Verifying Portfolio Dependencies (Guardrail)...")
    reg_data = _load_registry()
    
    for rid in run_ids:
        # 1. Check Registry Presence
        if rid not in reg_data:
            raise RuntimeError(f"[FATAL] Portfolio Dependency Guard: Run {rid} is missing from registry.")
            
        # 2. Check Physical Existence
        run_folder = RUNS_DIR / rid
        if not run_folder.exists():
            raise RuntimeError(f"[FATAL] Portfolio Dependency Guard: Run {rid} is missing from filesystem.")
            
    print("[ORCHESTRATOR] Dependency Guard Passed.")
    print("[ORCHESTRATOR] Verifying Artifact Integrity before Portfolio Evaluation...")
    for rid, symbol in zip(run_ids, symbols):
        mgr = PipelineStateManager(rid)
        manifest_path = mgr.run_dir / "manifest.json"
        if not manifest_path.exists():
            transition_run_state(rid, "FAILED")
            raise RuntimeError(f"Manifest missing for run {rid}")

        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        bt_dir = BACKTESTS_DIR / f"{clean_id}_{symbol}"
        required_artifacts = {
            "results_tradelevel.csv": bt_dir / "raw" / "results_tradelevel.csv",
            "results_standard.csv": bt_dir / "raw" / "results_standard.csv",
            "equity_curve.csv": bt_dir / "raw" / "equity_curve.csv",
        }
        batch_summary_file = BACKTESTS_DIR / f"batch_summary_{clean_id}.csv"
        if not batch_summary_file.exists():
            transition_run_state(rid, "FAILED")
            raise RuntimeError(f"Batch summary artifact missing during verification: {batch_summary_file}")
        manifest_keys = set(manifest["artifacts"].keys())
        required_keys = set(required_artifacts.keys())
        if manifest_keys != required_keys:
            transition_run_state(rid, "FAILED")
            raise RuntimeError(
                f"Manifest Tampering Detected! Key mismatch for run {rid}. Expected: {required_keys}, Found: {manifest_keys}"
            )

        for name, expected_hash in manifest["artifacts"].items():
            target_path = required_artifacts[name]
            if not target_path.exists():
                transition_run_state(rid, "FAILED")
                raise RuntimeError(f"Artifact missing during verification: {target_path}")
            current_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
            if current_hash != expected_hash:
                transition_run_state(rid, "FAILED")
                raise RuntimeError(f"Artifact Tampering Detected! {name} hash mismatch for run {rid}.")

        print(f"[ORCHESTRATOR] Verified Integrity: {rid}")

    cmd_args = [python_exe, "tools/portfolio_evaluator.py", clean_id, "--run-ids"] + run_ids
    run_command(cmd_args, "Stage-4 Evaluation")

    portfolio_ledger_path = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"
    if not portfolio_ledger_path.exists():
        raise PipelineExecutionError(
            f"Stage-4 ledger artifact missing: {portfolio_ledger_path}",
            directive_id=clean_id,
            run_ids=run_ids,
        )

    import pandas as pd

    try:
        df_ledger = pd.read_excel(portfolio_ledger_path)
        if "portfolio_id" not in df_ledger.columns or "constituent_run_ids" not in df_ledger.columns:
            raise PipelineExecutionError(
                f"Failed to resolve columns in Master Ledger.",
                directive_id=clean_id,
                run_ids=run_ids,
            )
        
        if df_ledger.empty:
            raise PipelineExecutionError(
                f"Stage-4 validation failed: {portfolio_ledger_path.name} is empty (0 data rows).",
                directive_id=clean_id,
                run_ids=run_ids,
            )
            
        matching_rows = df_ledger[df_ledger["portfolio_id"].astype(str) == clean_id]
        if len(matching_rows) != 1:
            raise PipelineExecutionError(
                f"Stage-4 validation failed: Expected exactly 1 row for {clean_id} in Master Ledger, found {len(matching_rows)}",
                directive_id=clean_id,
                run_ids=run_ids,
            )
            
        portfolio_row = matching_rows.iloc[0]
        raw_runs_str = str(portfolio_row["constituent_run_ids"]) if pd.notna(portfolio_row["constituent_run_ids"]) else ""
        saved_runs = [r.strip() for r in raw_runs_str.split(",") if r.strip()]
        if len(saved_runs) != len(symbols):
            raise PipelineExecutionError(
                f"Stage-4 validation failed: Expected {len(symbols)} constituent runs but found {len(saved_runs)}",
                directive_id=clean_id,
                run_ids=run_ids,
            )
            
        print(f"[GATE] Stage-4 artifact verified: {clean_id} present in Master Ledger with {len(saved_runs)} runs.")
    except Exception as err:
        if isinstance(err, PipelineExecutionError):
            raise
        raise PipelineExecutionError(
            f"Failed to read Master Ledger: {err}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from err

    try:
        from tools.report_generator import generate_backtest_report, generate_strategy_portfolio_report

        backtest_root = BACKTESTS_DIR
        strategy_id = p_conf.get("Strategy", p_conf.get("strategy"))
        print("[ORCHESTRATOR] Generating Deterministic Markdown Reports...")
        generate_backtest_report(clean_id, backtest_root)
        generate_strategy_portfolio_report(clean_id, project_root) # project_root here for code? usually reports go to outputs/ or repo
        if strategy_id and strategy_id != clean_id:
            generate_strategy_portfolio_report(strategy_id, project_root)
    except Exception as rep_err:
        import traceback

        traceback.print_exc()
        print(f"[ERROR] REPORT_GENERATION_FAILURE: {rep_err}")
        print("[WARN] Non-authoritative step failed. Directive state unaffected.")

    transition_directive_state(clean_id, "PORTFOLIO_COMPLETE")

    capital_wrapper_ok = False
    try:
        print("[ORCHESTRATOR] Running Step 8: Capital Wrapper...")
        run_command([python_exe, "tools/capital_wrapper.py", clean_id], "Capital Wrapper")
        print("[ORCHESTRATOR] Step 8: Capital Wrapper COMPLETE.")
        capital_wrapper_ok = True
    except Exception as cw_err:
        print(f"[ERROR] CAPITAL_WRAPPER_FAILURE: {cw_err}")
        print("[WARN] Capital wrapper failed. Directive state is unaffected (PORTFOLIO_COMPLETE).")
        print("[WARN] Re-run manually: python tools/capital_wrapper.py " + clean_id)

    try:
        if capital_wrapper_ok:
            print("[ORCHESTRATOR] Running Step 8.5: Profile Selector...")
            run_command([python_exe, "tools/profile_selector.py", clean_id], "Profile Selector")
            print("[ORCHESTRATOR] Step 8.5: Profile Selector COMPLETE.")
        else:
            print("[ORCHESTRATOR] Step 8.5 skipped (capital wrapper not completed).")
    except Exception as ps_err:
        print(f"[ERROR] PROFILE_SELECTOR_FAILURE: {ps_err}")
        print("[WARN] Profile selector failed. Directive state is unaffected (PORTFOLIO_COMPLETE).")
        print("[WARN] Re-run manually: python tools/profile_selector.py " + clean_id)

    try:
        print("[ORCHESTRATOR] Running Step 9: Deployable Artifact Verification...")
        deploy_root = STRATEGIES_DIR / clean_id / "deployable"
        profiles = ["CONSERVATIVE_V1", "DYNAMIC_V1", "FIXED_USD_V1"]
        step9_failures = []

        for prof in profiles:
            prof_dir = deploy_root / prof
            if not prof_dir.exists():
                step9_failures.append(f"  [{prof}] Profile directory missing: {prof_dir}")
                continue

            required_files = [
                "equity_curve.csv",
                "equity_curve.png",
                "deployable_trade_log.csv",
                "summary_metrics.json",
            ]
            for fname in required_files:
                if not (prof_dir / fname).exists():
                    step9_failures.append(f"  [{prof}] Missing artifact: {fname}")

            metrics_path = prof_dir / "summary_metrics.json"
            if metrics_path.exists():
                with open(metrics_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                diff = abs(m.get("final_equity", 0) - (m.get("starting_capital", 0) + m.get("realized_pnl", 0)))
                if diff >= 0.01:
                    step9_failures.append(f"  [{prof}] Equity math mismatch: diff={diff:.4f}")
                if m.get("final_equity", 0) <= 0:
                    step9_failures.append(f"  [{prof}] Final equity is zero or negative")

            eq_path = prof_dir / "equity_curve.csv"
            if eq_path.exists():
                with open(eq_path, newline="", encoding="utf-8") as cf:
                    reader = _csv.DictReader(cf)
                    for row_num, row in enumerate(reader, 1):
                        eq_val = float(row.get("equity", 1))
                        if eq_val <= 0:
                            step9_failures.append(f"  [{prof}] Negative equity at row {row_num}")
                            break

            tl_path = prof_dir / "deployable_trade_log.csv"
            if tl_path.exists() and metrics_path.exists():
                with open(tl_path, newline="", encoding="utf-8") as cf:
                    tl_rows = sum(1 for _ in cf) - 1
                expected_max = m.get("total_accepted", -1)
                expected_min = max(0, expected_max - m.get("max_concurrent_trades", 0))
                if not (expected_min <= tl_rows <= expected_max):
                    step9_failures.append(
                        f"  [{prof}] Trade log count {tl_rows} not in expected bounds [{expected_min}, {expected_max}]"
                    )

            if not step9_failures:
                print(f"[ORCHESTRATOR] Step 9 [{prof}]: All artifacts verified.")

        if step9_failures:
            print("[ERROR] DEPLOYABLE_INTEGRITY_FAILURE:")
            for line in step9_failures:
                print(line)
            print("[WARN] Deployable verification failed. Directive state unaffected (PORTFOLIO_COMPLETE).")
        else:
            print("[ORCHESTRATOR] Step 9: Deployable Artifact Verification COMPLETE.")
    except Exception as dv_err:
        print(f"[ERROR] DEPLOYABLE_INTEGRITY_FAILURE: {dv_err}")
        print("[WARN] Deployable verification failed. Directive state unaffected (PORTFOLIO_COMPLETE).")
