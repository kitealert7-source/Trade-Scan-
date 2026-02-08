
import sys
import pandas as pd
from pathlib import Path
import importlib.util

# Setup Project Root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def load_engine():
    """Load the Universal Research Engine execution loop dynamically."""
    engine_path = PROJECT_ROOT / "engine_dev/universal_research_engine/1.2.0/execution_loop.py"
    if not engine_path.exists():
        print(f"[FAIL] Engine not found at {engine_path}")
        sys.exit(1)
        
    spec = importlib.util.spec_from_file_location("execution_loop", engine_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class IntegrityStrategy:
    def __init__(self):
        self.name = "Integrity Check Strategy"

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Pass-through, no indicators needed for forced signals
        return df

    def check_entry(self, ctx) -> dict:
        idx = ctx['index']
        # Force Long Entry at Index 1
        if idx == 1:
            return {"signal": 1, "comment": "Forced_Long"}
        # Force Short Entry at Index 10
        if idx == 10:
            return {"signal": -1, "comment": "Forced_Short"}
        return None

    def check_exit(self, ctx) -> dict:
        idx = ctx['index']
        direction = ctx['direction']
        
        # Exit Long at Index 5
        if direction == 1 and idx == 5:
            return {"signal": 1, "comment": "Exit_Long"}
        
        # Exit Short at Index 15
        if direction == -1 and idx == 15:
            return {"signal": 1, "comment": "Exit_Short"}
            
        return None

def run_check():
    print("="*60)
    print("ENGINE INTEGRITY SELF-TEST")
    print("="*60)
    
    # 1. Load Engine
    try:
        engine_module = load_engine()
        print("[PASS] Engine Module Loaded")
    except Exception as e:
        print(f"[FAIL] Engine Load Error: {e}")
        sys.exit(1)

    # 2. Create Synthetic Data (20 bars)
    dates = pd.date_range(start="2024-01-01", periods=20, freq="4h")
    df = pd.DataFrame({
        "timestamp": dates,
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 100.0,
        "volume": 1000
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
