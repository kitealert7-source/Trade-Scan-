import os
import shutil
import json
import hashlib
from pathlib import Path
from datetime import datetime

# CONSTANTS
PROJECT_ROOT = Path(__file__).parent.parent
TARGET_DIR = PROJECT_ROOT / "tradescan" / "strategies" / "Range_Breakout02_highvol_audit_v1"

FILES_TO_COPY = [
    # Engine
    ("engine_dev/universal_research_engine/1.2.0/main.py", "engine/main.py"),
    ("engine_dev/universal_research_engine/1.2.0/execution_loop.py", "engine/execution_loop.py"),
    
    # Tools
    ("tools/run_stage1.py", "tools/run_stage1.py"),
    ("tools/stage2_compiler.py", "tools/stage2_compiler.py"),
    ("tools/stage3_compiler.py", "tools/stage3_compiler.py"),
    ("tools/portfolio_evaluator.py", "tools/portfolio_evaluator.py"),
    ("tools/run_pipeline.py", "tools/run_pipeline.py"),
    ("tools/execution_emitter_stage1.py", "tools/execution_emitter_stage1.py"),
    
    # Strategy
    ("strategies/Range_Breakout/strategy.py", "strategy/strategy.py"),
    
    # Indicators
    ("indicators/structure/range_breakout_session.py", "indicators/range_breakout_session.py"),
    
    # Directive
    ("backtest_directives/active/Range_Breakout02.txt", "directive/Range_Breakout02.txt"),
]

BROKER_SPECS_DIR = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"
SYMBOLS = [
    "AUDNZD", "AUDUSD", "EURAUD", "EURUSD", "GBPAUD", 
    "GBPNZD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"
]

def calculate_hash(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def main():
    print(f"Creating Audit Snapshot at: {TARGET_DIR}")
    
    if TARGET_DIR.exists():
        print(f"Target directory exists. Cleaning...")
        shutil.rmtree(TARGET_DIR)
    
    TARGET_DIR.mkdir(parents=True)
    
    manifest = {}
    
    # 1. Copy Files
    for source_rel, dest_rel in FILES_TO_COPY:
        src = PROJECT_ROOT / source_rel
        dst = TARGET_DIR / dest_rel
        
        if not src.exists():
            print(f"[ERROR] Source file missing: {src}")
            continue
            
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        
        # Verify symbolic link
        if os.path.islink(dst):
            print(f"[ERROR] Symlink detected at {dst}")
        
        manifest[dest_rel] = calculate_hash(dst)
        print(f"Copied: {source_rel} -> {dest_rel}")

    # 2. Copy Broker Specs
    spec_dir = TARGET_DIR / "broker_specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    
    for sym in SYMBOLS:
        src = BROKER_SPECS_DIR / f"{sym}.yaml"
        dst = spec_dir / f"{sym}.yaml"
        
        if src.exists():
            shutil.copy2(src, dst)
            manifest[f"broker_specs/{sym}.yaml"] = calculate_hash(dst)
            print(f"Copied Spec: {sym}")
        else:
            print(f"[WARN] Broker spec missing: {sym}")

    # 3. Create Metadata
    metadata = {
        "snapshot_timestamp_utc": datetime.utcnow().isoformat(),
        "engine_version": "1.2.0",
        "strategy": "Range_Breakout02",
        "variant": "High-Volatility",
        "regime_definition": "33/66 Percentile of Trade High-Low Range (execution_emitter_stage1.py)",
        "friction_assumptions": "Slippage 1.0 pip, Spread +50% (Validated)",
        "risk_model": "Fixed Dollar Risk ($250) + Max Concurrent ($1000)",
        "content_hash_method": "SHA256"
    }
    
    with open(TARGET_DIR / "AUDIT_METADATA.json", "w") as f:
        json.dump(metadata, f, indent=4)
        
    # 4. Save Manifest
    with open(TARGET_DIR / "FILE_HASH_MANIFEST.json", "w") as f:
        json.dump(manifest, f, indent=4)
        
    print("-" * 60)
    print(f"Snapshot Complete. Total Files: {len(manifest)}")
    print(f"Manifest saved to {TARGET_DIR / 'FILE_HASH_MANIFEST.json'}")

if __name__ == "__main__":
    main()
