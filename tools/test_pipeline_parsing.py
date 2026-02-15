
import sys
import os
from pathlib import Path

# Mock tools/run_pipeline.py import by adding to path
sys.path.append(os.path.join(os.getcwd(), 'tools'))
import run_pipeline

# Create a dummy directive
DIRECTIVE_PATH = Path("backtest_directives/active/TEST_PIPELINE.txt")
with open(DIRECTIVE_PATH, "w") as f:
    f.write("Strategy: TEST\n")
    f.write("Symbols:\n")
    f.write("AAA\n")
    f.write("BBB\n")
    f.write("Max Concurrent Positions: 2\n")

print(f"Created {DIRECTIVE_PATH}")

try:
    max_conc, sym_count = run_pipeline.parse_concurrency_config(DIRECTIVE_PATH)
    print(f"Parsed Max Concurrent: {max_conc}")
    print(f"Parsed Symbol Count: {sym_count}")
    
    if max_conc == 2 and sym_count == 2:
        print("SUCCESS: Parsing logic verified.")
    else:
        print("FAILURE: Parsing logic incorrect.")
        
finally:
    if DIRECTIVE_PATH.exists():
        os.remove(DIRECTIVE_PATH)
        print("Cleaned up.")
