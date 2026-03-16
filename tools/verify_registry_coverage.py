
import os
import yaml
from pathlib import Path

PROJECT_ROOT = Path(r"c:\Users\faraw\Documents\Trade_Scan")
INDICATORS_DIR = PROJECT_ROOT / "indicators"
REGISTRY_PATH = INDICATORS_DIR / "INDICATOR_REGISTRY.yaml"

def verify_coverage():
    with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
        registry = yaml.safe_load(f)
    
    indicators_in_registry = set(registry.get("indicators", {}).keys())
    
    # Map from module path to registry key
    module_to_key = {}
    for key, meta in registry.get("indicators", {}).items():
        module_to_key[meta.get("module_path")] = key

    files_on_disk = []
    missing = []
    
    for root, dirs, files in os.walk(INDICATORS_DIR):
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                path = Path(root) / file
                # Convert to module format: indicators.momentum.rsi
                rel_path = path.relative_to(PROJECT_ROOT)
                module_name = str(rel_path).replace(os.sep, ".").replace(".py", "")
                
                files_on_disk.append(module_name)
                
                if module_name not in module_to_key:
                    missing.append(module_name)

    nl = "\n"
    missing_str = f"- {nl.join(missing)}" if missing else "- None"
    files_str = f"- {nl.join(files_on_disk)}" if files_on_disk else "- None"

    report = f"""# Registry Coverage Report
Date: 2026-03-14

## Summary
- Total indicator files on disk: **{len(files_on_disk)}**
- Total indicators in registry: **{len(indicators_in_registry)}**
- Missing from registry: **{len(missing)}**

## Missing Indicators
{missing_str}

## Files on Disk
{files_str}
"""
    
    report_path = PROJECT_ROOT / "REGISTRY_COVERAGE_REPORT.md"
    report_path.write_text(report, encoding='utf-8')
    print(f"Coverage report generated: {len(missing)} missing.")

if __name__ == "__main__":
    verify_coverage()
