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
    _is_patch_sibling,
    _normalize_signature_hash,
    _strip_timeframe_segment,
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


class TestPatchSiblingCrossTF(unittest.TestCase):
    """Coverage for _is_patch_sibling and its helper _strip_timeframe_segment.

    Motivation: the PSBRK V4 sweep registers a 15M parent (P00) with 5M children
    (P01+) under the same idea/sweep slot. The old _is_patch_sibling stripped only
    the trailing _PNN, so cross-TF children failed the sibling check and required
    manual sweep_registry.yaml inserts (commits 807e217, ebf2da4, 0b1c0f0). This
    suite locks in the TF-aware behavior while preventing regressions on the
    same-TF path.
    """

    def test_cross_tf_same_family_is_sibling(self):
        # PSBRK V4: 15M parent + 5M children under the same idea/sweep.
        existing = "65_BRK_XAUUSD_15M_PSBRK_S01_V4_P00"
        incoming = "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P16"
        self.assertTrue(_is_patch_sibling(existing, incoming))

    def test_same_tf_different_p_is_sibling(self):
        # Pre-existing behavior must still hold.
        self.assertTrue(_is_patch_sibling(
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09",
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P15",
        ))

    def test_identical_names_not_sibling(self):
        # `_is_patch_sibling` requires distinct names.
        self.assertFalse(_is_patch_sibling(
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09",
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09",
        ))

    def test_different_sweep_not_sibling(self):
        # SNN must NOT be stripped — different sweeps stay distinct.
        self.assertFalse(_is_patch_sibling(
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09",
            "65_BRK_XAUUSD_5M_PSBRK_S02_V4_P00",
        ))

    def test_different_model_not_sibling(self):
        self.assertFalse(_is_patch_sibling(
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09",
            "65_BRK_XAUUSD_5M_FAKEBREAK_S01_V4_P00",
        ))

    def test_different_idea_not_sibling(self):
        self.assertFalse(_is_patch_sibling(
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09",
            "01_TREND_XAUUSD_5M_PSBRK_S01_V4_P09",
        ))

    def test_run_context_suffix_is_sibling(self):
        # The run-context suffix (__E152) must be tolerated on either side.
        self.assertTrue(_is_patch_sibling(
            "65_BRK_XAUUSD_15M_PSBRK_S01_V4_P00",
            "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P02__E152",
        ))

    def test_multi_token_filter_chain(self):
        # Names with filter tokens between MODEL and SNN (e.g. RSIAVG_TRENDFILT)
        # must still be recognised as cross-TF siblings.
        self.assertTrue(_is_patch_sibling(
            "01_TREND_XAUUSD_15M_RSIAVG_TRENDFILT_S04_V1_P00",
            "01_TREND_XAUUSD_5M_RSIAVG_TRENDFILT_S04_V1_P03",
        ))

    def test_strip_timeframe_segment_basic(self):
        self.assertEqual(
            _strip_timeframe_segment("65_BRK_XAUUSD_15M_PSBRK_S01_V4_P00"),
            "65_BRK_XAUUSD_PSBRK_S01_V4_P00",
        )
        self.assertEqual(
            _strip_timeframe_segment("01_TREND_XAUUSD_1H_RSIAVG_TRENDFILT_S04_V1_P00"),
            "01_TREND_XAUUSD_RSIAVG_TRENDFILT_S04_V1_P00",
        )
        self.assertEqual(
            _strip_timeframe_segment("02_VOL_SPX500_1D_VOLEXP_S01_V1_P00"),
            "02_VOL_SPX500_VOLEXP_S01_V1_P00",
        )

    def test_strip_timeframe_segment_preserves_symbol_digits(self):
        # `SPX500` contains a digit run that must NOT be stripped — the strip
        # is anchored to the canonical S/V/P tail, so symbol-internal digits
        # are safe.
        name = "02_VOL_SPX500_15M_VOLEXP_S01_V1_P00"
        stripped = _strip_timeframe_segment(name)
        self.assertEqual(stripped, "02_VOL_SPX500_VOLEXP_S01_V1_P00")
        self.assertIn("SPX500", stripped)

    def test_strip_timeframe_segment_idempotent_when_already_stripped(self):
        already = "65_BRK_XAUUSD_PSBRK_S01_V4_P00"
        self.assertEqual(_strip_timeframe_segment(already), already)


if __name__ == "__main__":
    unittest.main()
