
import sys
import json
import hashlib
import argparse
import pandas as pd
from pathlib import Path
import importlib.util

# Setup Project Root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- Single Source of Truth: import ENGINE_VERSION from runtime engine ---
_engine_main_path = PROJECT_ROOT / "engine_dev" / "universal_research_engine" / "v1_4_0" / "main.py"
_spec = importlib.util.spec_from_file_location("_engine_main", _engine_main_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ENGINE_VERSION = _mod.ENGINE_VERSION

py_version = f"v{ENGINE_VERSION.replace('.', '_')}"
ENGINE_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine" / py_version
TOOLS_ROOT = PROJECT_ROOT / "tools"
MANIFEST_PATH = PROJECT_ROOT / "engine_dev" / "universal_research_engine" / py_version / "engine_manifest.json"
TOOLS_MANIFEST = PROJECT_ROOT / "tools" / "tools_manifest.json"

def load_engine():
    """Load the Universal Research Engine execution loop dynamically."""
    engine_path = ENGINE_ROOT / "execution_loop.py"
    if not engine_path.exists():
        print(f"[FAIL] Engine not found at {engine_path}")
        sys.exit(1)
        
    spec = importlib.util.spec_from_file_location("execution_loop", engine_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_hashes():
    """Verify engine file hashes against the vaulted manifest (strict mode only)."""

    if not MANIFEST_PATH.exists():
        print(f"[FAIL] Manifest not found at {MANIFEST_PATH}")
        return False

    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    file_hashes = manifest.get("file_hashes", {})
    if not file_hashes:
        print("[FAIL] No file_hashes in manifest")
        return False

    failures = []
    for filename, expected_hash in file_hashes.items():
        # Skip SOP files (governance docs, not engine code)
        if filename.endswith(".md"):
            continue

        filepath = ENGINE_ROOT / filename
        if not filepath.exists():
            failures.append(f"  {filename}: FILE MISSING")
            continue

        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        actual_hash = sha256.hexdigest().upper()

        if actual_hash != expected_hash.upper():
            failures.append(f"  {filename}: HASH MISMATCH (expected {expected_hash[:16]}..., got {actual_hash[:16]}...)")

    if failures:
        print("[FAIL] Hash Verification Failed:")
        for f in failures:
            print(f)
        return False
    else:
        print(f"[PASS] Hash Verification: {len([k for k in file_hashes if not k.endswith('.md')])} engine files match manifest")
        return True

def verify_tools_integrity():
    """Verify critical tool hashes against tools_manifest.json (mandatory)."""
    if not TOOLS_MANIFEST.exists():
        print(f"[FAIL] Tools manifest not found at {TOOLS_MANIFEST}")
        return False

    with open(TOOLS_MANIFEST, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    # Fix 4: Manifest timing warning — warn if any file was modified after manifest was generated.
    # Warning-only: does NOT fail verification, does NOT auto-regenerate.
    generated_at_str = manifest.get("generated_at")
    if generated_at_str:
        try:
            from datetime import datetime, timezone
            manifest_ts = datetime.fromisoformat(generated_at_str).timestamp()
            file_hashes_keys = manifest.get("file_hashes", {}).keys()
            for filename in file_hashes_keys:
                fpath = TOOLS_ROOT / filename
                if fpath.exists():
                    file_mtime = fpath.stat().st_mtime
                    if file_mtime > manifest_ts:
                        print(f"[WARN] {filename} modified AFTER last manifest generation. Re-run generate_guard_manifest.py.")
        except Exception:
            pass  # Non-fatal — timestamp comparison failure should never block verification

    file_hashes = manifest.get("file_hashes", {})
    failures = []

    for filename, expected_hash in file_hashes.items():
        filepath = TOOLS_ROOT / filename
        if not filepath.exists():
            failures.append(f"  {filename}: TOOL MISSING")
            continue

        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        actual_hash = sha256.hexdigest().upper()

        if actual_hash != expected_hash.upper():
            failures.append(f"  {filename}: HASH MISMATCH")
    
    if failures:
        print("[FAIL] Tools Integrity Failed:")
        for f in failures:
            print(f)
        return False
    else:
        print(f"[PASS] Tools Integrity: {len(file_hashes)} critical tools match manifest")
        return True

class IntegrityStrategy:
    def __init__(self):
        self.name = "Integrity Check Strategy"
        # Explicit stop fields required by strict stop contract (session_opposite_range).
        # Values set to match synthetic test data (close=100.0, low=95.0, high=105.0).
        self.session_low = 95.0   # stop for long trades: below entry
        self.session_high = 105.0  # stop for short trades: above entry

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Pass-through, no indicators needed for forced signals
        return df

    def check_entry(self, ctx) -> dict:
        idx = ctx.index
        # Force Long Entry at Index 1
        if idx == 1:
            return {"signal": 1, "comment": "Forced_Long", "stop_price": 95.0}
        # Force Short Entry at Index 10
        if idx == 10:
            return {"signal": -1, "comment": "Forced_Short", "stop_price": 105.0}
        return None

    def check_exit(self, ctx) -> dict:
        idx = ctx.index
        direction = ctx.direction
        
        # Exit Long at Index 5
        if direction == 1 and idx == 5:
            return {"signal": 1, "comment": "Exit_Long"}
        
        # Exit Short at Index 15
        if direction == -1 and idx == 15:
            return {"signal": 1, "comment": "Exit_Short"}
            
        return None

def run_check():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["strict"], default="strict", help="Verification mode (strict only)")
    args = parser.parse_args()

    print("="*60)
    print(f"ENGINE INTEGRITY SELF-TEST (Mode: strict)")
    print("="*60)
    
    # 1. Load Engine
    try:
        engine_module = load_engine()
        print("[PASS] Engine Module Loaded")
    except Exception as e:
        print(f"[FAIL] Engine Load Error: {e}")
        sys.exit(1)

    # 1.5 Verify File Hashes Against Manifest
    if not verify_hashes():
        print("[FAIL] Engine files do not match vaulted manifest. Aborting.")
        sys.exit(1)

    # 1.6 Verify Tools Integrity
    if not verify_tools_integrity():
        print("[FAIL] Critical tools do not match tools_manifest. Aborting.")
        sys.exit(1)

    # 2. Create Synthetic Data (20 bars)
    dates = pd.date_range(start="2024-01-01", periods=20, freq="4h")
    df = pd.DataFrame({
        "timestamp": dates,
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 100.0,
        "volume": 1000,
        "volatility_regime": "normal",
        "trend_score": 0,
        "trend_regime": 0,
        "trend_label": "neutral",
        "atr": 5.0
    })
    
    # 3. Initialize Strategy
    strategy = IntegrityStrategy()
    
    # 4. Run Execution
    try:
        trades = engine_module.run_execution_loop(df, strategy)
        print(f"[INFO] Engine returned {len(trades)} trades")
    except Exception as e:
        print(f"[FAIL] Execution Loop Crashed: {e}")
        sys.exit(1)
        
    # 5. Assertions
    failures = []
    
    # Assert Count
    if len(trades) != 2:
        failures.append(f"Expected 2 trades, got {len(trades)}")
    
    # Assert Directions
    longs = [t for t in trades if t['direction'] == 1]
    shorts = [t for t in trades if t['direction'] == -1]
    
    if len(longs) != 1:
        failures.append(f"Expected 1 Long trade, got {len(longs)}")
    if len(shorts) != 1:
        failures.append(f"Expected 1 Short trade, got {len(shorts)}")
        
    # Assert Lifecycle and Data Quality
    for i, t in enumerate(trades):
        # 1. Price Validation
        if t.get('entry_price', 0) <= 0:
             failures.append(f"Trade {i} has invalid entry_price: {t.get('entry_price')}")
        if t.get('exit_price', 0) <= 0:
             failures.append(f"Trade {i} has invalid exit_price: {t.get('exit_price')}")
             
        # 2. Key Existence
        required_keys = ['entry_index', 'exit_index', 'direction', 'entry_timestamp', 'exit_timestamp']
        for k in required_keys:
            if k not in t:
                failures.append(f"Trade {i} missing key: {k}")
                
        # 3. Logic Validation
        if t['entry_index'] >= t['exit_index']:
            failures.append(f"Trade {i} entry_index ({t['entry_index']}) >= exit_index ({t['exit_index']})")

    # Specific Signal Consumption Checks
    # We forced Long at idx=1, Short at idx=10
    
    # Check Long
    trade_long = next((t for t in trades if t['entry_index'] == 1), None)
    if not trade_long:
        failures.append("Trade at index 1 (Forced Long) not found")
    elif trade_long['direction'] != 1:
        failures.append(f"Trade at index 1 should be Long (1), got {trade_long['direction']}")
        
    # Check Short
    trade_short = next((t for t in trades if t['entry_index'] == 10), None)
    if not trade_short:
        failures.append("Trade at index 10 (Forced Short) not found")
    elif trade_short['direction'] != -1:
        failures.append(f"Trade at index 10 should be Short (-1), got {trade_short['direction']}")

    # Final Verdict
    if failures:
        print("\n[FAIL] Integrity Check Failed:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\n[SUCCESS] Engine Logic Verified: Long and Short executed correctly.")
        print("="*60)
        sys.exit(0)

if __name__ == "__main__":
    run_check()
