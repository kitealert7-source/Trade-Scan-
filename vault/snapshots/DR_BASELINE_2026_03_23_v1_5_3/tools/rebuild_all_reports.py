import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
PYTHON_EXE = sys.executable

def main():
    print("Batch Recompiling Stage-2 Reports (Applying Decimalization Fix)...")
    print("=" * 60)
    
    count = 0
    errors = 0
    
    for folder in BACKTESTS_ROOT.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
            
        metadata_file = folder / "metadata" / "run_metadata.json"
        if not metadata_file.exists():
            continue
            
        print(f"[{count+1}] Recompiling {folder.name}...")
        
        try:
            # Run Stage-2 Compiler on this folder
            # This regenerates AK_Trade_Report.xlsx using the FIXED stage2_compiler.py (decimals not %)
            # and applies the FIXED format_excel_artifact.py
            cmd = [PYTHON_EXE, "tools/stage2_compiler.py", str(folder)]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL) # Suppress noisy output
            count += 1
        except subprocess.CalledProcessError:
            print(f"  [FAIL] Could not recompile {folder.name}")
            errors += 1
            
    print("=" * 60)
    print(f"Completed. Processed: {count}, Errors: {errors}")
    print("Now running Stage-3 Aggregation to rebuild Strategy_Master_Filter.xlsx...")
    
    # Run Stage-3
    try:
        subprocess.run([PYTHON_EXE, "tools/stage3_compiler.py"], check=True)
    except Exception as e:
        print(f"[FATAL] Stage-3 Failed: {e}")

if __name__ == "__main__":
    main()
