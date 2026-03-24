
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
_engine_main_path = PROJECT_ROOT / "engine_dev" / "universal_research_engine" / "v1_5_3" / "main.py"
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

class SessionLimitStrategy2:
    """
    Trade-management test: max_trades_per_session=2.
    Fires 3 entry signals in the same UTC day → engine must execute exactly 2.
    Signal bars: 0, 4, 8.  Entry bars (next_bar_open): 1, 5, (9 blocked).
    Exit bars: 3, 7.
    All bars fall within 2024-01-01 (1h freq, 24 bars).
    """
    name = "SessionLimitStrategy2"
    STRATEGY_SIGNATURE = {
        "trade_management": {
            "max_trades_per_session": 2,
            "session_reset": "utc_day",
        }
    }

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx) -> dict:
        if ctx.index in (0, 4, 8):
            return {"signal": 1, "stop_price": 90.0}  # 90 < low=95 → stop never fires
        return None

    def check_exit(self, ctx) -> bool:
        if ctx.direction == 1 and ctx.index in (3, 7, 11):
            return True
        return None


class UnlimitedSessionStrategy:
    """
    Trade-management test: max_trades_per_session omitted → unlimited.
    Same 3 signals in the same UTC day → engine must execute all 3.
    Entry bars: 1, 5, 9.  Exit bars: 3, 7, 11.
    """
    name = "UnlimitedSessionStrategy"
    # No STRATEGY_SIGNATURE → max_trades_per_session defaults to None (unlimited)

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx) -> dict:
        if ctx.index in (0, 4, 8):
            return {"signal": 1, "stop_price": 90.0}
        return None

    def check_exit(self, ctx) -> bool:
        if ctx.direction == 1 and ctx.index in (3, 7, 11):
            return True
        return None


class DiagnosticsStrategy:
    """
    Entry diagnostics test (v1.5.2).
    Fires one entry signal at bar 0 with entry_reference_price=100.0 and
    entry_reason='test_signal'.  The test df uses open=101.0, so:
      entry_price          = 101.0  (next_bar_open fill)
      entry_reference_price = 100.0
      entry_slippage        = 101.0 - 100.0 = 1.0
    Exit at bar 3.
    """
    name = "DiagnosticsStrategy"
    STRATEGY_SIGNATURE = {
        "trade_management": {
            "max_trades_per_session": None,
            "session_reset": "utc_day",
        }
    }

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx) -> dict:
        if ctx.index == 0:
            return {
                "signal": 1,
                "stop_price": 90.0,
                "entry_reference_price": 100.0,
                "entry_reason": "test_signal",
            }
        return None

    def check_exit(self, ctx) -> bool:
        if ctx.direction == 1 and ctx.index == 3:
            return True
        return None


def run_diagnostics_check(engine_module):
    """Assert entry_reference_price, entry_slippage, and entry_reason are captured."""
    print("\n[TEST] Entry Diagnostics (v1.5.2 — reference_price, slippage, reason)")
    df       = _make_session_test_df()
    strategy = DiagnosticsStrategy()
    failures = []

    try:
        trades = engine_module.run_execution_loop(df, strategy)
    except Exception as e:
        print(f"  [FAIL] Execution crashed: {e}")
        return False

    if len(trades) != 1:
        failures.append(f"  Expected 1 trade, got {len(trades)}")
        for f in failures:
            print(f)
        return False

    t = trades[0]

    # entry_reference_price
    if t.get('entry_reference_price') != 100.0:
        failures.append(
            f"  entry_reference_price: expected 100.0, got {t.get('entry_reference_price')}"
        )

    # entry_slippage = next_bar_open(101.0) - reference(100.0) = 1.0
    if t.get('entry_slippage') != 1.0:
        failures.append(
            f"  entry_slippage: expected 1.0, got {t.get('entry_slippage')}"
        )

    # entry_reason
    if t.get('entry_reason') != 'test_signal':
        failures.append(
            f"  entry_reason: expected 'test_signal', got {t.get('entry_reason')}"
        )

    if failures:
        for f in failures:
            print(f)
        return False

    print("  [PASS] entry_reference_price=100.0, entry_slippage=1.0, entry_reason='test_signal'")
    return True


def _make_session_test_df():
    """24 × 1h bars, all on 2024-01-01 (same UTC day). open=101.0 to verify next_bar_open fill."""
    dates = pd.date_range(start="2024-01-01", periods=24, freq="1h")
    return pd.DataFrame({
        "timestamp":        dates,
        "open":             101.0,   # Distinct from close — verifies next_bar_open uses open
        "high":             105.0,
        "low":              95.0,
        "close":            100.0,
        "volume":           1000,
        "volatility_regime": "normal",
        "trend_score":       0,
        "trend_regime":      0,
        "trend_label":       "neutral",
        "atr":               5.0,
    })


def run_session_limit_check(engine_module):
    """Assert max_trades_per_session=2 blocks the 3rd signal in the same session."""
    print("\n[TEST] Session Limit (max=2, 3 signals same day)")
    df       = _make_session_test_df()
    strategy = SessionLimitStrategy2()
    failures = []

    try:
        trades = engine_module.run_execution_loop(df, strategy)
    except Exception as e:
        print(f"  [FAIL] Execution crashed: {e}")
        return False

    if len(trades) != 2:
        failures.append(f"  Expected 2 trades, got {len(trades)}")

    entry_indices = {t['entry_index'] for t in trades}
    if entry_indices != {1, 5}:
        failures.append(f"  Expected entry_indices {{1, 5}}, got {entry_indices} (idx 9 should be blocked)")

    for t in trades:
        if t.get('entry_price') != 101.0:
            failures.append(f"  Trade {t['entry_index']}: entry_price should be 101.0 (open), got {t.get('entry_price')}")
        if t.get('stop_source') != 'STRATEGY':
            failures.append(f"  Trade {t['entry_index']}: stop_source should be STRATEGY, got {t.get('stop_source')}")

    if failures:
        for f in failures:
            print(f)
        return False

    print("  [PASS] Exactly 2 trades; 3rd signal correctly blocked; entry_price=101.0 (open)")
    return True


def run_unlimited_session_check(engine_module):
    """Assert omitting max_trades_per_session allows all 3 signals to execute."""
    print("\n[TEST] Unlimited Session (no max declared, 3 signals same day)")
    df       = _make_session_test_df()
    strategy = UnlimitedSessionStrategy()
    failures = []

    try:
        trades = engine_module.run_execution_loop(df, strategy)
    except Exception as e:
        print(f"  [FAIL] Execution crashed: {e}")
        return False

    if len(trades) != 3:
        failures.append(f"  Expected 3 trades, got {len(trades)}")

    entry_indices = {t['entry_index'] for t in trades}
    if entry_indices != {1, 5, 9}:
        failures.append(f"  Expected entry_indices {{1, 5, 9}}, got {entry_indices}")

    if failures:
        for f in failures:
            print(f)
        return False

    print("  [PASS] All 3 trades executed; no session limit enforced")
    return True


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
    # next_bar_open model: signal on bar N → entry executes at bar N+1.
    # Signal at idx=1 → entry_index=2 (Long)
    # Signal at idx=10 → entry_index=11 (Short)

    # Check Long
    trade_long = next((t for t in trades if t['entry_index'] == 2), None)
    if not trade_long:
        failures.append("Trade at index 2 (Forced Long, next_bar_open of signal@1) not found")
    elif trade_long['direction'] != 1:
        failures.append(f"Trade at index 2 should be Long (1), got {trade_long['direction']}")

    # Check Short
    trade_short = next((t for t in trades if t['entry_index'] == 11), None)
    if not trade_short:
        failures.append("Trade at index 11 (Forced Short, next_bar_open of signal@10) not found")
    elif trade_short['direction'] != -1:
        failures.append(f"Trade at index 11 should be Short (-1), got {trade_short['direction']}")

    # Check v1.5.0 diagnostic fields present in every trade
    for i, t in enumerate(trades):
        if 'exit_source' not in t:
            failures.append(f"Trade {i} missing field: exit_source")
        if 'stop_source' not in t:
            failures.append(f"Trade {i} missing field: stop_source")
        valid_exit_sources = {'STOP', 'TP', 'TIME_EXIT', 'SIGNAL_EXIT'}
        if t.get('exit_source') not in valid_exit_sources:
            failures.append(f"Trade {i} invalid exit_source: {t.get('exit_source')}")
        valid_stop_sources = {'STRATEGY', 'ENGINE_FALLBACK'}
        if t.get('stop_source') not in valid_stop_sources:
            failures.append(f"Trade {i} invalid stop_source: {t.get('stop_source')}")

    # Final Verdict — core test
    if failures:
        print("\n[FAIL] Integrity Check Failed:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("\n[SUCCESS] Engine Logic Verified: Long and Short executed correctly.")

    # --- v1.5.1 SESSION MANAGEMENT TESTS ---
    session_limit_ok    = run_session_limit_check(engine_module)
    unlimited_trades_ok = run_unlimited_session_check(engine_module)

    if not session_limit_ok or not unlimited_trades_ok:
        print("\n[FAIL] Session management tests failed.")
        sys.exit(1)

    print("\n[SUCCESS] All session management tests passed.")

    # --- v1.5.2 ENTRY DIAGNOSTICS TEST ---
    diagnostics_ok = run_diagnostics_check(engine_module)

    if not diagnostics_ok:
        print("\n[FAIL] Entry diagnostics test failed.")
        sys.exit(1)

    print("\n[SUCCESS] Entry diagnostics test passed.")
    print("="*60)
    sys.exit(0)

if __name__ == "__main__":
    run_check()
