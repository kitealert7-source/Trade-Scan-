
import unittest
import yaml
import os
import sys
from pathlib import Path

# Setup project root for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engines.indicator_warmup_resolver import resolve_strategy_warmup, RegistryFormulaError

REGISTRY_PATH = PROJECT_ROOT / "indicators" / "INDICATOR_REGISTRY.yaml"

class TestRegistryIntegrity(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            cls.registry = yaml.safe_load(f)
        cls.indicators = cls.registry.get("indicators", {})

    def test_required_fields(self):
        """Every indicator must have lookback, warmup, and input_columns."""
        required = ["lookback", "warmup", "input_columns"]
        for name, meta in self.indicators.items():
            for field in required:
                self.assertIn(field, meta, f"Indicator '{name}' missing required field '{field}'")

    def test_formula_resolution(self):
        """All formulas must resolve using default parameters."""
        for name, meta in self.indicators.items():
            try:
                # resolver uses default_parameters internally now
                # We pass an empty params dict to force it to use defaults.
                result = resolve_strategy_warmup([{"name": name, "params": {}}])
                self.assertIsInstance(result, int, f"Warmup for '{name}' did not resolve to an integer")
            except RegistryFormulaError as e:
                self.fail(f"Formula resolution failed for '{name}': {str(e)}")

    def test_summary_sync(self):
        """Summary counts must match actual indicators."""
        summary = self.registry.get("registry_summary", {})
        total = len(self.indicators)
        self.assertEqual(summary.get("total_indicators"), total, "Total indicator count mismatch")
        
        # Verify specific categorization if needed
        # (This depends on the classification field in each meta)
        regime_count = sum(1 for m in self.indicators.values() if m.get("classification") == "Regime")
        self.assertEqual(summary.get("by_category", {}).get("regime_count"), regime_count, "Regime count mismatch")

    def test_invalid_formula_detection(self):
        """Resolver must reject invalid formulas or missing parameters."""
        # This test uses a mock entry or we can rely on the resolver's error handling
        # Since we use real registry, we'll assume the registry is clean but 
        # let's verify the resolver raises on unknown params if we inject a bad one.
        from engines.indicator_warmup_resolver import _safe_eval_formula
        with self.assertRaises(RegistryFormulaError):
            _safe_eval_formula("non_existent_param * 2", {}, "test_ind")

if __name__ == "__main__":
    unittest.main()
