import os
import time
import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives" / "active"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "run_registry.json"

def copy_directive_from_completed(name: str) -> Path:
    src = PROJECT_ROOT / "backtest_directives" / "completed" / f"{name}.txt"
    dst = DIRECTIVES_DIR / f"{name}.txt"
    if src.exists():
        shutil.copy2(src, dst)
        
    return dst

def provision_and_patch_strategy(name: str):
    # Ensure directory exists
    target_strat_dir = PROJECT_ROOT / "strategies" / name
    target_strat_dir.mkdir(parents=True, exist_ok=True)
    
    p00_strat = PROJECT_ROOT / "strategies" / "06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P00" / "strategy.py"
    if p00_strat.exists():
        content = p00_strat.read_text(encoding="utf-8")
        content = content.replace("06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P00", name)
        (target_strat_dir / "strategy.py").write_text(content, encoding="utf-8")

def main():
    print("--- Test C: Concurrent Pipeline Execution ---")
    
    print("[INFO] Staging valid concurrent directives...")
    dir_a = copy_directive_from_completed("06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P01")
    dir_b = copy_directive_from_completed("06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P02")
    
    if not dir_a.exists() or not dir_b.exists():
        print("[ERROR] Failed to stage base directives.")
        return
        
    print("[INFO] Provisioning and patching strategies to bypass admission gate...")
    provision_and_patch_strategy("06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P01")
    provision_and_patch_strategy("06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P02")
    
    # Capture initial registry size
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        initial_reg_size = len(json.load(f))
        
    print("[INFO] Launching concurrent pipelines...")
    env = os.environ.copy()
    env["TRADE_SCAN_TEST_SKIP_ENGINE_INTEGRITY"] = "1"
    
    cmd_a = ["python", "tools/run_pipeline.py", dir_a.stem, "--skip-reports"]
    cmd_b = ["python", "tools/run_pipeline.py", dir_b.stem, "--skip-reports"]
    
    proc_a = subprocess.Popen(cmd_a, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc_b = subprocess.Popen(cmd_b, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    out_a, err_a = proc_a.communicate()
    out_b, err_b = proc_b.communicate()
    
    if proc_a.returncode == 0 and proc_b.returncode == 0:
        print("[INFO] Both pipelines completed successfully.")
        
        # Verify the registry added both runs safely without overwrites
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
            
        final_reg_size = len(registry)
        expected_size = initial_reg_size + 2 # Assuming 1 run per directive (XAUUSD)
        
        # Check if the directives are in registry
        found_a = any(run_data.get("directive_hash") == dir_a.stem for run_data in registry.values())
        found_b = any(run_data.get("directive_hash") == dir_b.stem for run_data in registry.values())
        
        if final_reg_size == expected_size and found_a and found_b:
            print("[PASS] Concurrent pipeline execution did not corrupt registry entries.")
        else:
            print(f"[FAIL] Registry size mismatch or missing runs! Expected: {expected_size}, Got: {final_reg_size}")
            print(f"       Found A: {found_a}, Found B: {found_b}")
            print(f"--- Output A ---\n{out_a}\n{err_a}")
            print(f"--- Output B ---\n{out_b}\n{err_b}")
            
    else:
        print(f"[ERROR] Pipeline executions failed: A={proc_a.returncode}, B={proc_b.returncode}")
        if proc_a.returncode != 0:
            print(f"--- Output A ---\n{out_a}\n{err_a}")
        if proc_b.returncode != 0:
            print(f"--- Output B ---\n{out_b}\n{err_b}")
        
    # Cleanup
    dir_a.unlink()
    dir_b.unlink()

if __name__ == "__main__":
    main()
