import tempfile
import textwrap
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.sweep_registry_gate import (
    SweepRegistryError,
    _hash_for_storage,
    _hash_signature,
    _hashes_match,
    _normalize_signature_hash,
)

# Minimal directive body — only the behavioural fields that go into the hash.
_DIRECTIVE_TMPL = textwrap.dedent("""\
    test:
      name: TEST_HASH_TF_{tf}
      family: TST
      strategy: TEST_HASH_TF_{tf}
      broker: OctaFX
      timeframe: {tf}
      start_date: 2024-01-01
      end_date: 2026-01-01

    symbols:
      - XAUUSD

    indicators:
      - indicators.volatility.atr

    execution_rules:
      pyramiding: false
      entry_when_flat_only: true
      reset_on_exit: true
      entry_logic:
        long: "close > open"
      stop_loss:
        type: fixed_atr
        atr_multiple: 1.5
      take_profit:
        enabled: false
""")


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

    def test_cross_tf_directives_produce_different_hashes(self):
        """Same strategy logic on different timeframes must NOT collide.

        Root cause that triggered this test: normalize_signature() excludes
        `timeframe` (non-behavioral for strategy logic), so _hash_signature()
        previously produced identical hashes for P00=15M and P01=5M clones,
        causing new_pass.py to raise SWEEP_COLLISION and block auto-registration.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d15m = Path(tmp) / "TST_15m.txt"
            d5m  = Path(tmp) / "TST_5m.txt"
            d15m.write_text(_DIRECTIVE_TMPL.format(tf="15m"), encoding="utf-8")
            d5m.write_text(_DIRECTIVE_TMPL.format(tf="5m"),  encoding="utf-8")

            h15m = _hash_signature(d15m)
            h5m  = _hash_signature(d5m)

            self.assertNotEqual(
                h15m, h5m,
                "Cross-TF directives must produce distinct hashes — "
                "same hash would cause SWEEP_COLLISION in new_pass.py."
            )

    def test_same_tf_directive_is_stable(self):
        """_hash_signature must be deterministic: same file → same hash."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "TST_1h.txt"
            d.write_text(_DIRECTIVE_TMPL.format(tf="1h"), encoding="utf-8")
            self.assertEqual(_hash_signature(d), _hash_signature(d))

    def test_no_timeframe_field_does_not_raise(self):
        """Directive without a timeframe key must still produce a hash (no crash)."""
        body = textwrap.dedent("""\
            test:
              name: TEST_NOTF
              family: TST
              strategy: TEST_NOTF
              broker: OctaFX
              start_date: 2024-01-01
              end_date: 2026-01-01

            symbols:
              - XAUUSD

            indicators:
              - indicators.volatility.atr

            execution_rules:
              pyramiding: false
              entry_when_flat_only: true
              reset_on_exit: true
              entry_logic:
                long: "close > open"
              stop_loss:
                type: fixed_atr
                atr_multiple: 1.5
              take_profit:
                enabled: false
        """)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "TST_notf.txt"
            d.write_text(body, encoding="utf-8")
            result = _hash_signature(d)
            self.assertIsInstance(result, str)
            self.assertEqual(len(result), 64)


if __name__ == "__main__":
    unittest.main()
