"""
Run Watchdog — recovers stale runs stuck in active FSM states.

Scans TradeScan_State/runs/ for run_state.json files whose heartbeat_ts
exceeds the threshold.  Routes all state mutations through
PipelineStateManager.abort() so transitions are FSM-validated, audited,
and atomically written.
"""

import json
from datetime import datetime, timezone
from config.state_paths import RUNS_DIR
from config.status_enums import RUN_TERMINAL_STATES


def recover_stale_runs(threshold_minutes=10):
    """
    Scans the state cluster for runs permanently stuck in active states.
    If pipeline aborted unexpectedly, their `heartbeat_ts` will be older than the threshold.
    """
    if not RUNS_DIR.exists():
        return

    from tools.pipeline_utils import PipelineStateManager

    threshold_seconds = threshold_minutes * 60
    current_time = datetime.now(timezone.utc).timestamp()

    stale_found = 0

    for run_folder in RUNS_DIR.iterdir():
        if not run_folder.is_dir() or len(run_folder.name) != 24:
            continue

        state_file = run_folder / "run_state.json"
        if not state_file.exists():
            continue

        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            current_state = data.get("current_state")

            # Skip terminal states — nothing to recover
            if current_state in RUN_TERMINAL_STATES or current_state == "IDLE":
                continue

            heartbeat = data.get("heartbeat_ts")
            if not heartbeat:
                continue

            age = current_time - heartbeat
            if age > threshold_seconds:
                print(f"[WATCHDOG] Stale active run detected ({age:.1f}s old) -> aborting ({run_folder.name})")

                # Route through FSM — gains audit logging, validation, atomic write
                directive_id = data.get("directive_id")
                mgr = PipelineStateManager(run_folder.name, directive_id=directive_id)
                aborted = mgr.abort(reason="WATCHDOG_TIMEOUT")

                if not aborted:
                    print(f"[WATCHDOG] Could not abort {run_folder.name} (state={current_state}) — FSM rejected transition.")
                    continue

                # Sync to run registry (non-authoritative — failure here is non-fatal)
                if directive_id:
                    try:
                        from tools.orchestration.run_registry import update_run_state
                        registry_path = RUNS_DIR / directive_id / "run_registry.json"
                        if registry_path.exists():
                            update_run_state(
                                registry_path,
                                directive_id,
                                run_folder.name,
                                "ABORTED",
                                last_error="Watchdog timeout (abandoned active state).",
                                termination_reason="WATCHDOG_TIMEOUT",
                            )
                    except Exception as reg_err:
                        print(f"[WATCHDOG] Could not update registry for {run_folder.name}: {reg_err}")

                stale_found += 1

        except Exception as e:
            print(f"[WATCHDOG] Failed to parse state for {run_folder.name}: {e}")

    if stale_found > 0:
        print(f"[WATCHDOG] Recovered {stale_found} stale FSM states.")
