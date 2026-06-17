"""
Regression coverage for the rerun-variant naming contract (Model B).

A /rerun-backtest variant rotates a __E### suffix onto BOTH the filename and
test.name while test.strategy stays at the base. Two governance gates must
recognize that layout as already-namespaced and identity-valid:

  1. tools/convert_promoted_directives._is_already_namespaced  (auto-migration)
  2. tools/namespace_gate._extract_name_fields                 (Stage -0.30)

Both previously enforced the stale Model A (filename == test.strategy), which
rejected every rotated variant (PORT/basket: loud "Ambiguous idea_id";
single-active-idea family e.g. VOL: silent re-rename). These tests pin the
reconciled Model B across both gates for the three families the operator named:
PORT basket, MR single-asset, and VOL single-active-idea.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.convert_promoted_directives import _is_already_namespaced, convert_promoted
from tools.namespace_gate import _extract_name_fields, NamespaceValidationError


# (label, base == test.strategy, variant_stem == filename == test.name)
VARIANTS = [
    ("PORT_basket",
     "90_PORT_AUDJPYAUDNZD_15M_COINTREV_V3_L30_GP_ZCRS_BBK25__E240109",
     "90_PORT_AUDJPYAUDNZD_15M_COINTREV_V3_L30_GP_ZCRS_BBK25__E240109__E001"),
    ("MR_single_asset",
     "15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00",
     "15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00__E002"),
    ("VOL_single_active_idea",
     "02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P01",
     "02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P01__E001"),
]


def _data(name, strategy):
    return {"test": {"name": name, "strategy": strategy, "timeframe": "15m"}}


def _write_directive(directory, stem, name, strategy):
    body = (
        "test:\n"
        f"  name: {name}\n"
        f"  strategy: {strategy}\n"
        "  timeframe: 15m\n"
        "symbols:\n"
        "  - EURUSD\n"
    )
    (directory / f"{stem}.txt").write_text(body, encoding="utf-8")


class TestMigrationRecognizer(unittest.TestCase):
    """convert_promoted_directives._is_already_namespaced (auto-migration gate)."""

    def test_recognizes_each_variant(self):
        for label, base, variant in VARIANTS:
            with self.subTest(label):
                ok = _is_already_namespaced(Path(f"{variant}.txt"), _data(variant, base))
                self.assertTrue(ok, f"{label}: rerun variant not recognized as namespaced")

    def test_standard_namespaced_still_recognized(self):
        sid = "03_TREND_EURUSD_1D_RSIAVG_S01_V1_P00"
        self.assertTrue(_is_already_namespaced(Path(f"{sid}.txt"), _data(sid, sid)))

    def test_legacy_unnamespaced_not_recognized(self):
        sid = "fx_portability_test"
        self.assertFalse(_is_already_namespaced(Path(f"{sid}.txt"), _data(sid, sid)))

    def test_adversarial_unrelated_strategy_base_rejected(self):
        # filename == test.name but test.strategy is an unrelated base -> not namespaced
        self.assertFalse(
            _is_already_namespaced(
                Path("90_PORT_FOO__E001.txt"),
                _data("90_PORT_FOO__E001", "TOTALLY_DIFFERENT_BASE"),
            )
        )

    def test_adversarial_lowercase_suffix_rejected(self):
        self.assertFalse(
            _is_already_namespaced(
                Path("90_PORT_FOO__e001.txt"),
                _data("90_PORT_FOO__e001", "90_PORT_FOO"),
            )
        )


class TestNamespaceGateIdentity(unittest.TestCase):
    """namespace_gate._extract_name_fields (Stage -0.30 admission identity check)."""

    def test_accepts_each_variant(self):
        for label, base, variant in VARIANTS:
            with self.subTest(label):
                stem, name, strategy = _extract_name_fields(
                    _data(variant, base), Path(f"{variant}.txt")
                )
                self.assertEqual(stem, variant)
                self.assertEqual(name, variant)
                self.assertEqual(strategy, base)

    def test_accepts_standard_namespaced(self):
        sid = "03_TREND_EURUSD_1D_RSIAVG_S01_V1_P00"
        self.assertEqual(_extract_name_fields(_data(sid, sid), Path(f"{sid}.txt")),
                         (sid, sid, sid))

    def test_rejects_filename_not_tracking_test_name(self):
        # Model B: the filename must equal test.name (here the stem drops the suffix).
        with self.assertRaises(NamespaceValidationError):
            _extract_name_fields(
                _data("15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00__E002",
                      "15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00"),
                Path("15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00.txt"),
            )

    def test_rejects_unrelated_strategy_base(self):
        with self.assertRaises(NamespaceValidationError):
            _extract_name_fields(
                _data("90_PORT_FOO__E001", "TOTALLY_DIFFERENT_BASE"),
                Path("90_PORT_FOO__E001.txt"),
            )

    def test_rejects_lowercase_suffix(self):
        with self.assertRaises(NamespaceValidationError):
            _extract_name_fields(
                _data("90_PORT_FOO__e001", "90_PORT_FOO"),
                Path("90_PORT_FOO__e001.txt"),
            )


class TestConvertPromotedEndToEnd(unittest.TestCase):
    """End-to-end: the auto-migration must SKIP rotated variants, not rename/error them."""

    def test_variants_skipped_no_rename_no_error(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "INBOX"
            inbox.mkdir()
            backup = Path(td) / "backup"
            strat_root = Path(td) / "strategies"
            strat_root.mkdir()

            for _label, base, variant in VARIANTS:
                _write_directive(inbox, variant, variant, base)

            before = {p.name for p in inbox.glob("*.txt")}

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                convert_promoted(
                    source_dir=inbox,
                    backup_dir=backup,
                    rename_strategies=False,
                    strategy_root=strat_root,
                )
            out = buf.getvalue()

            after = {p.name for p in inbox.glob("*.txt")}
            self.assertEqual(before, after, "a rotated variant was renamed by the migration")
            for _label, _base, variant in VARIANTS:
                self.assertTrue((inbox / f"{variant}.txt").exists(),
                                f"{variant} missing after migration")

            # Positive proof the SKIP path was taken (not the error-caught path that
            # only coincidentally leaves a multi-idea-family file in place).
            self.assertIn("files skipped: 3", out)
            self.assertIn("files converted: 0", out)
            self.assertIn("namespace errors: 0", out)


if __name__ == "__main__":
    unittest.main()
