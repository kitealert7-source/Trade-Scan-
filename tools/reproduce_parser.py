from pathlib import Path
from tools.pipeline_utils import parse_directive

# Create a dummy directive file
dummy_path = Path("dummy_directive.txt")
with open(dummy_path, "w") as f:
    f.write("symbols:\n  - AUDUSD\n  - EURUSD\n")

try:
    parsed = parse_directive(dummy_path)
    print(f"Parsed keys: {list(parsed.keys())}")
    print(f"Value for 'symbols': {parsed.get('symbols')}")
    print(f"Value for 'Symbols': {parsed.get('Symbols')}")
finally:
    if dummy_path.exists():
        dummy_path.unlink()
