import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.sweep_registry_gate import (
    SweepRegistryError,
    _hash_for_storage,
    _hashes_match,
    _normalize_signature_hash,
)


class TestSweepRegistryHashCompat(unittest.TestCase):
    def test_short_hash_matches_full_prefix(self):
        full = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        short = full[:16]
        self.assertTrue(_hashes_match(short, full))
        self.assertTrue(_hashes_match(full, short))

    def test_hash_storage_tuple(self):
        full = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
        stored, short = _hash_for_storage(full)
        self.assertEqual(stored, full)
        self.assertEqual(short, full[:16])

    def test_invalid_hash_raises(self):
        with self.assertRaises(SweepRegistryError):
            _normalize_signature_hash("not-a-hash")


if __name__ == "__main__":
    unittest.main()
