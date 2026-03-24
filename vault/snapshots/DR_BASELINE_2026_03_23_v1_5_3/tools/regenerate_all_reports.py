import sys
from pathlib import Path

project_root = Path(r"c:\Users\faraw\Documents\Trade_Scan")
sys.path.insert(0, str(project_root))

from tools.report_generator import generate_backtest_report

backtest_root = Path(r"c:\Users\faraw\Documents\TradeScan_State")
backtest_dir = backtest_root / "backtests"

directives = set()
for d in backtest_dir.iterdir():
    if d.is_dir() and not d.name.startswith("PF_"):
        parts = d.name.rsplit("_", 1)
        if len(parts) == 2:
            directives.add(parts[0])

print("Regenerating all historical reports securely...")
success = 0
for directive in sorted(directives):
    try:
        generate_backtest_report(directive, backtest_dir)
        success += 1
    except Exception as e:
        print(f"Skipped {directive}: {e}")

print(f"Successfully processed {success} directives across state.")
