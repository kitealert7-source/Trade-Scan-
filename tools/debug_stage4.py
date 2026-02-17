import sys
import subprocess
import traceback

print("Debugging Stage-4 Failure for Range_Breakout01...")

try:
    # Run portfolio_evaluator directly
    result = subprocess.run(
        [sys.executable, "tools/portfolio_evaluator.py", "Range_Breakout01"],
        capture_output=True,
        text=True,
        check=True
    )
    print("SUCCESS")
    print(result.stdout)
except subprocess.CalledProcessError as e:
    print("FAILURE")
    print("STDOUT:", e.stdout)
    print("STDERR:", e.stderr)
except Exception:
    traceback.print_exc()
