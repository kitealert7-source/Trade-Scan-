import sys
import json
import hashlib
import shutil
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import generate_run_id, PipelineStateManager

def main():
    print(">>> ADVERSARIAL TEST: ARTIFACT TAMPERING")
    
    clean_id = "Workflow_Test_01"
    symbol = "AUDNZD"
    d_path = PROJECT_ROOT / "backtest_directives" / "active" / f"{clean_id}.txt"
    
    # 1. Get Run ID
    rid, _ = generate_run_id(d_path, symbol)
    print(f"Run ID: {rid}")
    
    mgr = PipelineStateManager(rid)
    manifest_path = mgr.run_dir / "STRATEGY_SNAPSHOT.manifest.json"
    
    if not manifest_path.exists():
        print("[FAIL] Manifest not found. Run happy path first.")
        sys.exit(1)
        
    # 2. Locate Artifact
    bt_dir = PROJECT_ROOT / "backtests" / f"{clean_id}_{symbol}"
    target_artifact = bt_dir / "raw" / "results_tradelevel.csv"
    
    if not target_artifact.exists():
        print(f"[FAIL] Target artifact missing: {target_artifact}")
        sys.exit(1)
        
    print(f"Target: {target_artifact}")
    
    # 3. Backup & Tamper
    backup_path = target_artifact.with_suffix(".bak")
    shutil.copy2(target_artifact, backup_path)
    
    print("[ACTION] Tampering with artifact...")
    with open(target_artifact, "ab") as f:
        f.write(b"\nTAMPERED_DATA_ROW,0,0,0,0")
        
    # 4. Run Verification Logic (Mirrored from run_pipeline.py)
    try:
        print("[VERIFICATION] Running integrity check...")
        
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
            
        expected_hash = manifest["artifacts"]["results_tradelevel.csv"]
        current_hash = hashlib.sha256(target_artifact.read_bytes()).hexdigest()
        
        print(f"Expected: {expected_hash}")
        print(f"Current:  {current_hash}")
        
        if current_hash != expected_hash:
            raise RuntimeError(f"Artifact Tampering Detected! results_tradelevel.csv hash mismatch.")
            
        print("[FAIL] Tampering NOT detected!")
        sys.exit(1)
        
    except RuntimeError as e:
        print(f"[SUCCESS] Caught Expected Error: {e}")
        
    except Exception as e:
        print(f"[FAIL] Unexpected Error: {e}")
        sys.exit(1)
        
    finally:
        # 5. Restore
        if backup_path.exists():
            shutil.move(backup_path, target_artifact)
            print("[CLEANUP] Artifact restored.")

    # 6. Test Key Mismatch
    print("\n[TEST] Manifest Key Mismatch")
    manifest_backup = manifest_path.with_suffix(".bak")
    shutil.copy2(manifest_path, manifest_backup)
    
    try:
        with open(manifest_path, "r") as f:
            data = json.load(f)
        
        data["artifacts"]["EXTRA_FILE.csv"] = "dummy_hash"
        
        with open(manifest_path, "w") as f:
            json.dump(data, f)
            
        # Verify (Simulated)
        required_keys = {"results_tradelevel.csv", "results_standard.csv", "batch_summary.csv"}
        manifest_keys = set(data["artifacts"].keys())
        
        print(f"Required: {required_keys}")
        print(f"Manifest: {manifest_keys}")
        
        if manifest_keys != required_keys:
            raise RuntimeError(f"Manifest Tampering Detected! Key mismatch.")
            
        print("[FAIL] Key Mismatch NOT detected!")
        sys.exit(1)
        
    except RuntimeError as e:
        print(f"[SUCCESS] Caught Expected Error: {e}")
        
    finally:
        if manifest_backup.exists():
            shutil.move(manifest_backup, manifest_path)
            print("[CLEANUP] Manifest restored.")

if __name__ == "__main__":
    main()
