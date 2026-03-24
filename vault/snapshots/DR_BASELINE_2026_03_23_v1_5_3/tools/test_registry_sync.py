import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path("C:/Users/faraw/Documents/Trade_Scan")

import sys
sys.path.insert(0, str(PROJECT_ROOT))
from tools.system_registry import _load_registry, _save_registry_atomic, reconcile_registry
RUNS_DIR = PROJECT_ROOT / "runs"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "run_registry.json"

def test_orphan_run():
    print("--- Test A: Orphan Run ---")
    orphan_id = "orphan123456"
    orphan_dir = RUNS_DIR / orphan_id / "data"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    
    # Run reconciliation
    reconcile_registry()
    
    # Check registry
    registry = _load_registry()
    if orphan_id in registry and registry[orphan_id]["tier"] == "sandbox":
        print(f"[PASS] Orphan run '{orphan_id}' correctly registered as sandbox.")
    else:
        print(f"[FAIL] Orphan run '{orphan_id}' was NOT handled correctly.")
        
    # Cleanup
    shutil.rmtree(RUNS_DIR / orphan_id)
    del registry[orphan_id]
    _save_registry_atomic(registry)

def test_ghost_registry():
    print("--- Test B: Ghost Registry ---")
    ghost_id = "ghost654321"
    
    # Create ghost entry
    registry = _load_registry()
    registry[ghost_id] = {
        "run_id": ghost_id,
        "tier": "sandbox",
        "status": "complete",
        "created_at": "2026-01-01T00:00:00Z",
        "directive_hash": "ghost_test",
        "artifact_hash": "deadbeef"
    }
    _save_registry_atomic(registry)
    
    # Ensure physical folder does NOT exist
    ghost_dir = RUNS_DIR / ghost_id
    if ghost_dir.exists():
        shutil.rmtree(ghost_dir)
        
    # Run reconciliation
    reconcile_registry()
    
    # Check registry
    registry = _load_registry()
    if ghost_id in registry and registry[ghost_id]["status"] == "invalid":
        print(f"[PASS] Ghost registry entry '{ghost_id}' correctly marked as invalid.")
    else:
        print(f"[FAIL] Ghost registry entry '{ghost_id}' was NOT marked invalid.")
        
    # Cleanup
    del registry[ghost_id]
    _save_registry_atomic(registry)

def main():
    test_orphan_run()
    test_ghost_registry()

if __name__ == "__main__":
    main()
