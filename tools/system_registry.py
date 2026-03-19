import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
import hashlib

from config.state_paths import RUNS_DIR, REGISTRY_DIR, STRATEGIES_DIR, SELECTED_DIR

PROJECT_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = REGISTRY_DIR / "run_registry.json"

def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_registry_atomic(data: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    
    # Atomic rename (replace existing)
    if os.name == 'nt':
        if REGISTRY_PATH.exists():
            os.replace(tmp_path, REGISTRY_PATH)
        else:
            tmp_path.rename(REGISTRY_PATH)
    else:
        tmp_path.rename(REGISTRY_PATH)

def log_run_to_registry(run_id: str, status: str, directive_id: str):
    """
    Log a run into the master lifecycle ledger.
    Extracts the artifact_hash from the run_state.json if available.
    """
    reg = _load_registry()
    
    # Try to extract the computed artifact_hash from run_state
    state_file = RUNS_DIR / run_id / "run_state.json"
    artifact_hash = None
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                artifact_hash = state_data.get("artifact_hash")
        except Exception:
            pass
            
    # If the run already exists, update status and possibly hash. Otherwise create new tier: sandbox.
    if status == "complete":
        # Verification Guard: Ensure core artifacts exist physically
        run_dir = RUNS_DIR / run_id
        required = [
            run_dir / "manifest.json",
            run_dir / "data" / "results_tradelevel.csv",
            run_dir / "data" / "results_standard.csv",
            run_dir / "data" / "equity_curve.csv"
        ]
        if not all(p.exists() for p in required):
            print(f"[INTEGRITY] Run {run_id} missing core artifacts. Downgrading status to 'failed'.")
            status = "failed"

    if run_id in reg:
        reg[run_id]["status"] = status
        if artifact_hash and not reg[run_id].get("artifact_hash"):
            reg[run_id]["artifact_hash"] = artifact_hash
    else:
        reg[run_id] = {
            "run_id": run_id,
            "tier": "sandbox",
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "directive_hash": directive_id,
            "artifact_hash": artifact_hash
        }
        
    _save_registry_atomic(reg)

def get_active_portfolio_runs() -> set:
    """Scan strategies/ for portfolio_composition.json files and collect active dependencies."""
    strategies_dir = STRATEGIES_DIR
    if not strategies_dir.exists():
        return set()
        
    active_runs = set()
    for fname in ["portfolio_composition.json", "portfolio_metadata.json"]:
        for comp_file in strategies_dir.rglob(fname):
            try:
                with open(comp_file, "r") as f:
                    data = json.load(f)
                    run_ids = data.get("constituent_run_ids", [])
                    if isinstance(run_ids, list):
                        active_runs.update(run_ids)
            except Exception:
                continue
    return active_runs

def reconcile_registry() -> dict:
    """
    Startup sweep to ensure consistency between registry and physical disk.
    - Physical folder but missing from registry -> inject as sandbox.
    - In registry but physical folder missing -> mark invalid.
    - Portfolio requires missing dependency -> hard crash.
    
    Returns:
        dict: Mismatch details for callers (e.g., gates).
    """
    reg = _load_registry()
    runs_dir = RUNS_DIR
    
    results = {
        "orphaned_on_disk": [],
        "missing_from_disk": [],
        "invalid_in_registry": []
    }
    
    # 1. Physical vs Registry (Across both Sandbox and Candidate boundaries)
    physical_runs = set()
    for directory in [RUNS_DIR, SELECTED_DIR]: # Explicitly check selected (candidates)
        if directory.exists():
            for item in directory.iterdir():
                if item.is_dir() and (item / "data").exists():
                    physical_runs.add(item.name)
        elif directory == RUNS_DIR:
             # Runs dir must exist or we have no sandbox
             pass
                
    dirty = False
    
    # Missing from registry
    for phys_id in physical_runs:
        if phys_id not in reg:
            print(f"[RECONCILE] Recovered orphaned physical run {phys_id} -> sandbox.")
            results["orphaned_on_disk"].append(phys_id)
            reg[phys_id] = {
                "run_id": phys_id,
                "tier": "sandbox",
                "status": "complete", # Assume complete if it has a data folder
                "created_at": datetime.now(timezone.utc).isoformat(),
                "directive_hash": "recovered",
                "artifact_hash": None
            }
            dirty = True
            
    # Physically missing but in registry
    for run_id, data in list(reg.items()):
        if run_id not in physical_runs:
            if data.get("status") == "invalid":
                results["invalid_in_registry"].append(run_id)
                continue
                
            if not (runs_dir / run_id).exists():
                print(f"[RECONCILE] Registry entry {run_id} missing physical folder -> marked invalid.")
                results["missing_from_disk"].append(run_id)
                reg[run_id]["status"] = "invalid"
                dirty = True
                
    # 3. Candidate Location Alignment (Auto-Repair)
    for run_id, data in reg.items():
        if data.get("tier") == "candidate" and data.get("status") == "complete":
            src = RUNS_DIR / run_id
            dst = SELECTED_DIR / run_id
            if src.exists() and not dst.exists():
                print(f"[RECONCILE] Detected candidate {run_id} in sandbox. Auto-repairing physical location...")
                try:
                    SELECTED_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                    # We don't need to set dirty here as registry data itself hasn't changed, 
                    # but reconciliation is about filesystem alignment.
                except Exception as e:
                    print(f"[ERROR] Auto-repair migration failed for {run_id}: {e}")
                
    if dirty:
        _save_registry_atomic(reg)

    # AUTO-CLEAN: remove newly-invalid run_ids from portfolio_metadata.json files
    newly_invalid = set(results["missing_from_disk"])
    if newly_invalid:
        for meta_file in STRATEGIES_DIR.rglob("portfolio_metadata.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                original = meta.get("constituent_run_ids", [])
                cleaned = [r for r in original if r not in newly_invalid]
                if len(cleaned) != len(original):
                    meta["constituent_run_ids"] = cleaned
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=4)
                    removed = set(original) - set(cleaned)
                    print(f"[RECONCILE] Auto-cleaned stale run_ids {removed} from {meta_file}")
            except Exception as e:
                print(f"[RECONCILE] Warning: could not clean {meta_file}: {e}")

    # 2. Portfolio Dependency Check
    active_portfolio_runs = get_active_portfolio_runs()
    for dep_id in active_portfolio_runs:
        if dep_id not in physical_runs or reg.get(dep_id, {}).get("status") == "invalid":
            raise RuntimeError(f"[FATAL] Consistency Violation: Portfolio heavily depends on missing/invalid run {dep_id}.")
            
    print("[RECONCILE] Registry alignment complete.")
    return results
