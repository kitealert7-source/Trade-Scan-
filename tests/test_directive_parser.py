"""
Directive Parser Safety Tests.

Tests the YAML-safe parser contract in pipeline_utils.parse_directive().
Uses only unittest and tempfile -- no external frameworks.
"""
import sys
import unittest
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import parse_directive


class TestDuplicateKeyDetection(unittest.TestCase):
    """Test 1 -- Duplicate keys in YAML raise ValueError."""

    def test_duplicate_key_raises(self):
        yaml_content = (
            "name: test\n"
            "broker: OctaFX\n"
            "broker: IC_Markets\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                parse_directive(path)
            self.assertIn("DUPLICATE", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)


class TestCollisionDetection(unittest.TestCase):
    """Test 2 -- test: sub-key colliding with root key raises ValueError."""

    def test_root_collision_raises(self):
        yaml_content = (
            "broker: A\n"
            "test:\n"
            "  broker: B\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                parse_directive(path)
            self.assertIn("COLLISION", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)


class TestNestedStructurePreserved(unittest.TestCase):
    """Test 3 -- Nested YAML structures are dicts, not flattened."""

    def test_nested_dicts_preserved(self):
        yaml_content = (
            "name: test_directive\n"
            "range_definition:\n"
            "  source: timeframe_data\n"
            "  window: 100\n"
            "execution_rules:\n"
            "  direction_restriction: none\n"
            "test:\n"
            "  broker: OctaFX\n"
            "  timeframe: 15m\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            parsed = parse_directive(path)
            self.assertIsInstance(parsed["range_definition"], dict)
            self.assertIsInstance(parsed["execution_rules"], dict)
            self.assertIsInstance(parsed["test"], dict)
            # Verify test: keys were hoisted to root
            self.assertEqual(parsed["broker"], "OctaFX")
            self.assertEqual(parsed["timeframe"], "15m")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
