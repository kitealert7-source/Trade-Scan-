"""
run_cleanup.py — Automatic Cleanup for Preflight Failures
Purpose: Immediately removes provisioned run containers if Preflight halts execution.
Authority: Failure Audit Fix 1
"""

from pathlib import Path
import shutil
from config.state_paths import RUNS_DIR

def cleanup_provisioned_runs(run_ids: list[str]) -> None:
    """
    Cleans up empty provisioned run folders.
    Safety rule: NEVER delete runs containing data/ or results_tradelevel.csv.
    """
    for r_id in run_ids:
        r_path = RUNS_DIR / r_id
        if not r_path.exists() or not r_path.is_dir():
            continue

        run_state_file = r_path / "run_state.json"
        strategy_file = r_path / "strategy.py"
        data_dir = r_path / "data"
        results_file = r_path / "data" / "results_tradelevel.csv"
        manifest_file = r_path / "manifest.json"
        crash_log = r_path / "crash_trace.log"
        
        # Only cleanup if it's an empty "headless" run footprint
        if (
            run_state_file.exists()
            and not strategy_file.exists()
            and not data_dir.exists()
            and not results_file.exists()
            and not manifest_file.exists()
            and not crash_log.exists()
        ):
            print(f"[ORCHESTRATOR] Cleanup: Removing abandoned run container {r_id}")
            try:
                shutil.rmtree(r_path)
            except Exception as e:
                print(f"[WARN] Failed to cleanly remove abandoned run {r_id}: {e}")
