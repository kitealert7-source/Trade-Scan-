
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from governance.preflight import run_preflight

def main():
    active_dir = PROJECT_ROOT / "backtest_directives" / "active"
    txt_files = list(active_dir.glob("*.txt"))
    
    if len(txt_files) != 1:
        print(f"[FATAL] Expected exactly 1 active directive, found {len(txt_files)}")
        sys.exit(1)
        
    directive_path = txt_files[0]
    print(f"Running Preflight on: {directive_path.name}")
    
    # Run Check
    # Signature: run_preflight(directive_path: str, engine_name: str, engine_version: str)
    decision, explanation, scope = run_preflight(str(directive_path), "Universal_Research_Engine", "1.2.0")
    
    print("-" * 60)
    print(f"DECISION: {decision}")
    print("-" * 60)
    print(f"Explanation: {explanation}")
    
    if decision == "ALLOW_EXECUTION":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
