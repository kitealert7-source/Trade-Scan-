import sys
import os
import unittest
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, asdict

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "engine_dev/universal_research_engine/1.3.0"))

# Import target modules
import execution_loop
import execution_emitter_stage1
import stage2_compiler

@dataclass
class MockStrategy:
    def prepare_indicators(self, df):
        # Mocking indicator preparation
        # Add required columns
        df['volatility_regime'] = 'normal'
        df['linreg_regime'] = 1
        df['linreg_regime_htf'] = 1
        df['kalman_regime'] = 1
        df['trend_persistence'] = 1
        df['efficiency_ratio_regime'] = 1
        return df

    def check_entry(self, ctx):
        if ctx['index'] % 10 == 0:
            return {"signal": 1}
        return None

    def check_exit(self, ctx):
        if ctx['bars_held'] >= 5:
            return True
        return False

class TestEngineV130(unittest.TestCase):
    def setUp(self):
        # Create dummy dataframe
        self.df = pd.DataFrame({
            'close': [100 + i for i in range(100)],
            'high': [100 + i + 1 for i in range(100)],
            'low': [100 + i - 1 for i in range(100)],
            'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='1h').astype(str)
        })
        self.strategy = MockStrategy()

    def test_execution_loop_capture(self):
        print("\nTesting execution_loop.py capture logic...")
        trades = execution_loop.run_execution_loop(self.df.copy(), self.strategy)
        self.assertTrue(len(trades) > 0)
        
        t = trades[0]
        self.assertIn('volatility_regime', t)
        self.assertIn('trend_score', t)
        self.assertIn('trend_regime', t)
        self.assertIn('trend_label', t)
        
        self.assertEqual(t['volatility_regime'], 'normal')
        # sum of 5 components = 5 -> trend_score should be 5
        self.assertEqual(t['trend_score'], 5)
        # 5 >= 3 -> trend_regime should be 2
        self.assertEqual(t['trend_regime'], 2)
        # 2 -> trend_label should be 'strong_up'
        self.assertEqual(t['trend_label'], 'strong_up')
        print("[OK] Execution loop correctly captures market state.")

    def test_emitter_validation(self):
        print("\nTesting validation in execution_emitter_stage1.py...")
        
        valid_trade = execution_emitter_stage1.RawTradeRecord(
            strategy_name="test", parent_trade_id=1, sequence_index=1,
            entry_timestamp="2023-01-01", exit_timestamp="2023-01-02",
            direction=1, entry_price=100, exit_price=105, pnl_usd=5,
            r_multiple=1, bars_held=5, 
            volatility_regime="normal", 
            trend_score=5, trend_regime=2, trend_label="strong_up"
        )
        
        # Should pass
        try:
            execution_emitter_stage1.emit_stage1(
                [valid_trade], 
                execution_emitter_stage1.Stage1Metadata(
                    run_id="test_run", strategy_name="test", symbol="TEST", timeframe="1h",
                    date_range_start="2023-01-01", date_range_end="2023-01-02",
                    execution_timestamp_utc="now", engine_name="test", engine_version="1.3.0", broker="test",
                    reference_capital_usd=10000
                ),
                "directive", "directive.txt", Path("./test_output")
            )
            print("[OK] Valid trade emission passed.")
        except Exception as e:
            self.fail(f"Emission failed for valid trade: {e}")

        # Invalid trade (missing volatility)
        invalid_trade = execution_emitter_stage1.RawTradeRecord(
            strategy_name="test", parent_trade_id=2, sequence_index=1,
            entry_timestamp="2023-01-01", exit_timestamp="2023-01-02",
            direction=1, entry_price=100, exit_price=105, pnl_usd=5,
            r_multiple=1, bars_held=5, 
            volatility_regime=None,  # MISSING
            trend_score=5, trend_regime=2, trend_label="strong_up"
        )
        
        with self.assertRaises(ValueError):
            execution_emitter_stage1.emit_stage1(
                [invalid_trade], 
                 execution_emitter_stage1.Stage1Metadata(
                    run_id="test_run", strategy_name="test", symbol="TEST", timeframe="1h",
                    date_range_start="2023-01-01", date_range_end="2023-01-02",
                    execution_timestamp_utc="now", engine_name="test", engine_version="1.3.0", broker="test",
                    reference_capital_usd=10000
                ),
                "directive", "directive.txt", Path("./test_output")
            )
        print("[OK] Missing volatility_regime raises ValueError.")

    def test_stage2_strict_grouping(self):
        print("\nTesting strict grouping in stage2_compiler.py...")
        
        # Valid trades
        valid_trades = [{
            "pnl_usd": "100", "entry_price": "100", "exit_price": "101",
            "volatility_regime": "low"
        }]
        
        try:
            metrics = stage2_compiler._compute_metrics_from_trades(valid_trades, 10000)
            print("[OK] Stage-2 metrics computed for valid trades.")
        except Exception as e:
             self.fail(f"Stage-2 failed for valid trades: {e}")
             
        # Invalid trades (missing regime)
        invalid_trades = [{
            "pnl_usd": "100", 
            # Missing volatility_regime
        }]
        
        with self.assertRaisesRegex(ValueError, "Stage-2 CRITICAL"):
            stage2_compiler._compute_metrics_from_trades(invalid_trades, 10000)
        print("✓ Missing volatility_regime in Stage-2 raises critical error.")

if __name__ == '__main__':
    unittest.main()
