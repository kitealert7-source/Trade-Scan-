
from pathlib import Path
import yaml

project_root = Path(__file__).parent.parent
specs_dir = project_root / "data_access" / "broker_specs" / "OctaFx"

symbols = ["AUDNZD", "EURAUD", "GBPAUD", "GBPNZD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURUSD", "GBPUSD"]

for sym in symbols:
    file_path = specs_dir / f"{sym}.yaml"
    if file_path.exists():
        content = file_path.read_text(encoding="utf-8")
        if "contract_size: null" in content:
            new_content = content.replace("contract_size: null", "contract_size: 100000.0")
            file_path.write_text(new_content, encoding="utf-8")
            print(f"Fixed {sym}.yaml")
        else:
            print(f"Skipped {sym}.yaml (already set or format differs)")
    else:
        print(f"File not found: {sym}.yaml")
