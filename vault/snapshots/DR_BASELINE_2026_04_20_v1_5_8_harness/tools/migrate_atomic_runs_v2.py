"""
migrate_atomic_runs_v2.py -- One-Time Migration Script
Upgrades TradeScan artifacts to the Atomic Run Container v2 Architecture.
"""

import sys
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
BACKTESTS_DIR = PROJECT_ROOT / "backtests"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "run_registry.json"

def get_file_bytes(path: Path) -> bytes:
    if not path.exists():
        return b""
    with open(path, "rb") as f:
        return f.read()

def compute_artifact_hash(data_dir: Path) -> str:
    """Deterministic hash of the trade-level outputs"""
    files = ["results_tradelevel.csv", "results_standard.csv", "equity_curve.csv"]
    hash_contents = [get_file_bytes(data_dir / f) for f in files]
    return hashlib.sha256(b"".join(hash_contents)).hexdigest()

def scan_backtest_folders() -> dict:
    mapping = {}
    if not BACKTESTS_DIR.exists():
        return mapping
        
    print(f"[*] Scanning {BACKTESTS_DIR.name}/ for run_metadata...")
    for item in BACKTESTS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            meta = item / "metadata" / "run_metadata.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    rid = data.get("run_id")
                    if rid:
                        mapping[rid] = item
                except Exception:
                    pass
    return mapping

def scan_active_portfolios() -> set:
    runs = set()
    if not STRATEGIES_DIR.exists():
        return runs
    for p_dir in STRATEGIES_DIR.iterdir():
        if p_dir.is_dir() and not p_dir.name.startswith("."):
            comp = p_dir / "portfolio_composition.json"
            if comp.exists():
                try:
                    data = json.loads(comp.read_text(encoding="utf-8"))
                    c_runs = data.get("constituent_run_ids", [])
                    runs.update(c_runs)
                except Exception:
                    pass
    return runs

def main():
    print("================================================")
    print(" ATOMIC RUN CONTAINER MIGRATION v2")
    print("================================================\n")
    
    backtest_map = scan_backtest_folders()
    print(f"[*] Found {len(backtest_map)} mapped runs in backtests/\n")
    
    active_portfolios = scan_active_portfolios()
    print(f"[*] Found {len(active_portfolios)} runs actively bound to portfolios\n")
    
    registry = {}
    if REGISTRY_PATH.exists():
        try:
            registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
            
    migrated_count = 0
    
    if RUNS_DIR.exists():
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
                
            rid = run_dir.name
            data_dir = run_dir / "data"
            
            # Step 1: Consolidate
            if not data_dir.exists():
                print(f"[MIGRATE] Upgrading container for {rid}...")
                data_dir.mkdir(parents=True, exist_ok=True)
                
                # Copy from backtests/
                bt_folder = backtest_map.get(rid)
                if bt_folder:
                    bt_raw = bt_folder / "raw"
                    bt_meta = bt_folder / "metadata"
                    
                    if bt_raw.exists():
                        for f in bt_raw.glob("*"):
                            shutil.copy2(f, data_dir / f.name)
                            
                    if bt_meta.exists():
                        for f in bt_meta.glob("*"):
                            shutil.copy2(f, data_dir / f.name)
                            
            # Check completeness
            if (data_dir / "results_tradelevel.csv").exists():
                status = "complete"
                a_hash = compute_artifact_hash(data_dir)
            else:
                status = "failed"
                a_hash = None
                
            # Inject into state
            state_file = run_dir / "run_state.json"
            if state_file.exists():
                try:
                    state_data = json.loads(state_file.read_text(encoding="utf-8"))
                    state_data["artifact_hash"] = a_hash
                    with open(state_file, "w") as f:
                        json.dump(state_data, f, indent=4)
                except Exception as e:
                    print(f"  [WARN] Failed to inject hash into run_state.json for {rid}: {e}")
                    
            # Inject into Registry
            tier = "portfolio" if rid in active_portfolios else "sandbox"
            registry[rid] = {
                "run_id": rid,
                "tier": tier,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "directive_hash": "legacy_v1",
                "artifact_hash": a_hash
            }
            
            migrated_count += 1

    # Save Registry Atomically
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=4)
    # Windows-safe overwrite
    import os
    if os.name == 'nt' and REGISTRY_PATH.exists():
        os.replace(tmp_path, REGISTRY_PATH)
    else:
        tmp_path.rename(REGISTRY_PATH)
        
    print(f"\n[SUCCESS] Migrated {migrated_count} runs to Atomic v2 Schema.")
    print(f"          Registry regenerated at {REGISTRY_PATH.relative_to(PROJECT_ROOT)}.")

if __name__ == "__main__":
    main()
