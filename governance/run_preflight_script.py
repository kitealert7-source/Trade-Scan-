
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from governance.preflight import run_preflight

directive_path = "backtest_directives/active/SPX04.txt"
engine_name = "universal_research_engine"
engine_version = "1.2.0"

decision, reason, scope = run_preflight(directive_path, engine_name, engine_version)

print(f"DECISION: {decision}")
print(f"REASON: {reason}")
if scope:
    print(f"SCOPE: {scope}")
