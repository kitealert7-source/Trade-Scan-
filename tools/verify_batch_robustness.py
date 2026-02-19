
import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from tools.pipeline_utils import get_canonical_hash, parse_directive
except ImportError as e:
    print(f"[FAIL] Import Error: {e}")
    sys.exit(1)

def test_canonical_stability():
    print("--- Test: Canonical Stability ---")
    config1 = {
        "strategy": "StratA",
        "symbol": "EURUSD",
        "params": {"a": 1, "b": 2}
    }
    # Reordered keys
    config2 = {
        "params": {"b": 2, "a": 1},
        "symbol": "EURUSD",
        "strategy": "StratA"
    }
    
    hash1 = get_canonical_hash(config1)
    hash2 = get_canonical_hash(config2)
    
    if hash1 == hash2:
        print(f"[PASS] Hash match: {hash1}")
    else:
        print(f"[FAIL] Hash mismatch: {hash1} != {hash2}")
        return False
    return True

def test_sensitivity():
    print("\n--- Test: Sensitivity ---")
    config1 = {"a": 1}
    config2 = {"a": 2} # Changed value
    
    hash1 = get_canonical_hash(config1)
    hash2 = get_canonical_hash(config2)
    
    if hash1 != hash2:
        print(f"[PASS] Hash distinct: {hash1} vs {hash2}")
    else:
        print(f"[FAIL] Hash collision (bad): {hash1}")
        return False
    return True

def test_failure_isolation():
    print("\n--- Test: Failure Isolation ---")
    import subprocess
    import shutil
    
    active_dir = PROJECT_ROOT / "backtest_directives" / "active"
    held_dir = PROJECT_ROOT / "backtest_directives" / "temp_held"
    held_dir.mkdir(exist_ok=True)
    
    # 1. Move existing directives to held
    existing = list(active_dir.glob("*.txt"))
    moved = []
    for f in existing:
        dest = held_dir / f.name
        try:
            shutil.move(str(f), str(dest))
            moved.append((dest, f))
        except Exception as e:
            print(f"[WARN] Failed to move {f}: {e}")
            
    # 2. Create TEST_FAIL.txt
    fail_directive = active_dir / "TEST_FAIL.txt"
    fail_content = """
Strategy: StratFail
Symbols:
- AUDUSD
- INVALID_SYMBOL
Timeframe: 1d
Start Date: 2024-01-01
End Date: 2024-01-05
Broker: OctaFx
    """
    fail_directive.write_text(fail_content.strip(), encoding="utf-8")
    
    try:
        cmd = [sys.executable, "tools/run_stage1.py"]
        print(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        
        output = result.stdout + result.stderr
        
        # Check for expected signals
        aud_run = "AUDUSD" in output and ("SUCCESS" in output or "NO_TRADES" in output)
        invalid_fail = "INVALID_SYMBOL" in output and "FAILED" in output
        summary_present = "BATCH EXECUTION SUMMARY" in output
        
        # Determine success
        if aud_run and invalid_fail and summary_present:
            print("\n[PASS] Isolation Successful.")
            passed = True
        else:
            print("\n[FAIL] Isolation Failed.")
            print(f"[OUTPUT SNAPSHOT]\n{output[-1000:]}")
            passed = False
            
    finally:
        # 3. Cleanup
        if fail_directive.exists():
            fail_directive.unlink()
            
        # 4. Restore
        for dest, src in moved:
            if dest.exists():
                shutil.move(str(dest), str(src))
        held_dir.rmdir()
        
    return passed

def main():
    print("Verifying Batch Robustness...")
    
    if not test_canonical_stability():
        sys.exit(1)
        
    if not test_sensitivity():
        sys.exit(1)
        
    print("Running Failure Isolation Test...")
    if not test_failure_isolation():
        sys.exit(1)
        
    print("\n[SUCCESS] All Robustness Tests Passed.")

if __name__ == "__main__":
    main()
