"""Compatibility tests for legacy FilterStack import cleanup in provisioner."""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.strategy_provisioner import _update_existing_strategy


class TestStrategyProvisionerCompat(unittest.TestCase):
    def test_removes_legacy_pipeline_utils_filterstack_import(self):
        content = """from tools.pipeline_utils import FilterStack

class Strategy:
    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {}
    # --- STRATEGY SIGNATURE END ---
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "strategy.py"
            path.write_text(content, encoding="utf-8")
            ok = _update_existing_strategy(
                path,
                signature={"x": 1},
                required_imports=["from engines.filter_stack import FilterStack"],
            )
            self.assertTrue(ok)
            updated = path.read_text(encoding="utf-8")
            self.assertNotIn("from tools.pipeline_utils import FilterStack", updated)
            self.assertEqual(updated.count("from engines.filter_stack import FilterStack"), 1)


if __name__ == "__main__":
    unittest.main()
