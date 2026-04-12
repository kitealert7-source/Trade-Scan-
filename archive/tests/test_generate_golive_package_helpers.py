import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.generate_golive_package import (
    _conversion_pairs_for_symbols,
    extract_session_reset,
    extract_symbols_from_directive,
)


class TestGoLivePackageHelpers(unittest.TestCase):
    def test_extract_symbols_from_directive(self):
        d = {"symbols": ["eurusd", "USDJPY", "EURUSD"]}
        symbols = extract_symbols_from_directive(d)
        self.assertEqual(symbols, ["EURUSD", "USDJPY"])

    def test_session_reset_default(self):
        value, source = extract_session_reset({"order_placement": {"type": "market"}})
        self.assertEqual(value, "utc_day")
        self.assertEqual(source, "default")

    def test_conversion_pairs_and_non_fx_assumption(self):
        pairs, non_fx = _conversion_pairs_for_symbols(["EURUSD", "USDJPY", "NAS100"])
        self.assertIn("USDJPY", pairs)
        self.assertIn("NAS100", non_fx)


if __name__ == "__main__":
    unittest.main()
