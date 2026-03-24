import os
import json
import shutil
import time
from datetime import datetime, timezone
from config.state_paths import RUNS_DIR

def recover_stale_runs(threshold_minutes=10):
    """
    Scans the state cluster for runs permanently stuck in `RUNNING`.
    If pipeline aborted unexpectedly, their `heartbeat_ts` will be older than the threshold.
    """
    if not RUNS_DIR.exists():
        return
        
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
            if current_state != "STAGE_1_COMPLETE" and "RUNNING" not in current_state: 
                # Our heavy step is symbol execution stage, usually wrapped or state is held
                # Standard Pipeline runs might not explicitly transition state to literally `RUNNING`.
                # Wait, review: The original implementation plan says:
                # "If current_state == RUNNING AND heartbeat_ts is older..."
                # Let's match the exact spec loosely. If we use PREFLIGHT_COMPLETE_SEMANTICALLY_VALID 
                # (which is when runner claims it) or generally just look at `heartbeat_ts`.
                pass
                
            # Improved robust rule: ANY state that has a heartbeat older than threshold and isn't terminal.
            terminal_states = ["COMPLETE", "FAILED", "ABORTED", "IDLE"]
            if current_state in terminal_states:
                continue
                
            heartbeat = data.get("heartbeat_ts")
            if not heartbeat:
                continue
                
            age = current_time - heartbeat
            if age > threshold_seconds:
                print(f"[WATCHDOG] Stale active run detected ({age:.1f}s old) -> marked ABORTED ({run_folder.name})")
                
                # Append ABORTED to history block
                old_state = current_state
                data["history"].append({
                    "from": old_state,
                    "to": "ABORTED",
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "reason": "WATCHDOG_TIMEOUT"
                })
                data["current_state"] = "ABORTED"
                data["last_transition"] = datetime.now(timezone.utc).isoformat() + "Z"
                
                # Write atomic
                temp_file = state_file.with_suffix(".tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                shutil.move(str(temp_file), str(state_file))
                
                # Sync to registry
                directive_id = data.get("directive_id")
                if directive_id:
                    from tools.orchestration.run_registry import update_run_state
                    registry_path = RUNS_DIR / directive_id / "run_registry.json"
                    if registry_path.exists():
                        try:
                            update_run_state(
                                registry_path, 
                                directive_id, 
                                run_folder.name, 
                                "ABORTED", 
                                last_error="Watchdog timeout (abandoned RUNNING lock).",
                                termination_reason="WATCHDOG_TIMEOUT"
                            )
                        except Exception as reg_err:
                            print(f"[WATCHDOG] Could not update registry for {run_folder.name}: {reg_err}")
                
                stale_found += 1
                
        except Exception as e:
            print(f"[WATCHDOG] Failed to parse state for {run_folder.name}: {e}")
            
    if stale_found > 0:
        print(f"[WATCHDOG] Recovered {stale_found} stale FSM states.")
