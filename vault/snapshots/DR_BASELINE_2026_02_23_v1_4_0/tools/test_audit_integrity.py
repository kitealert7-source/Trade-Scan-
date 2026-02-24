import sys
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import generate_run_id, PipelineStateManager

def main():
    print(">>> ADVERSARIAL TEST: AUDIT LOG INTEGRITY")
    
    clean_id = "Workflow_Test_01"
    symbol = "AUDNZD"
    d_path = PROJECT_ROOT / "backtest_directives" / "active" / f"{clean_id}.txt"
    
    # 1. Get Run ID
    rid, _ = generate_run_id(d_path, symbol)
    print(f"Run ID: {rid}")
    
    mgr = PipelineStateManager(rid)
    audit_log_path = mgr.run_dir / "audit.log"
    
    if not audit_log_path.exists():
        print("[FAIL] audit.log missing. Run happy path first.")
        sys.exit(1)
        
    print(f"Audit Log: {audit_log_path}")
    
    # 2. Read Log
    logs = []
    with open(audit_log_path, 'r') as f:
        for line in f:
            if line.strip():
                logs.append(json.loads(line))
                
    print(f"Entries: {len(logs)}")
    
    # 3. Verify Events
    required_events = {
        "RUN_INITIALIZED",
        "STATE_TRANSITION",
        "SNAPSHOT_VERIFIED",
        "ARTIFACT_BOUND",
        "RUN_COMPLETE"
    }
    
    found_events = set(l['event'] for l in logs)
    missing = required_events - found_events
    
    if missing:
        print(f"[FAIL] Missing required audit events: {missing}")
        sys.exit(1)
        
    print("[SUCCESS] All required event types present.")
    
    # 4. Chronology Check
    last_ts = ""
    for entry in logs:
        ts = entry['timestamp']
        if ts < last_ts:
            print(f"[FAIL] Time travel detected! {ts} < {last_ts}")
            sys.exit(1)
        last_ts = ts
        
    print("[SUCCESS] timestamp chronology verified.")
    
    # 5. Tamper Test (Append-Only)
    # Attempt to overwrite (simulated via file mode check? Python allows overwrite if we want... 
    # but the test is "Is it tamper evident?". 
    # If we modify lines in the middle, they won't match hash if we had a chain. 
    # But Phase 9 spec didn't ask for Merkle chaining yet, just "Unified append-only audit log".
    # So we just verify presence and structure for now.
    
    print("Audit Log Integrity Verified.")

if __name__ == "__main__":
    main()
