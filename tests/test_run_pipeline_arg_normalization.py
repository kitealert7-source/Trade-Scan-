"""
Regression coverage for run_pipeline.normalize_directive_arg.

A single-directive CLI arg may be a bare id, a bare id with .txt, or a full /
relative path (the form the /rerun-backtest SKILL Quick Reference documents).
All must normalize to the bare directive_id the admission + state machinery
keys on. Before this normalization a path-form arg kept its directory prefix
and the run aborted at admission with "Directive ... not found in INBOX".
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_pipeline import normalize_directive_arg
from tools.orchestration.pre_execution import find_directive_path

BARE = "90_PORT_AUDJPYAUDNZD_15M_COINTREV_V3_L30_GP_ZCRS_BBK25__E240109__E001"


class TestNormalizeDirectiveArg(unittest.TestCase):

    def test_bare_id_unchanged(self):
        self.assertEqual(normalize_directive_arg(BARE), BARE)

    def test_bare_id_with_extension(self):
        self.assertEqual(normalize_directive_arg(f"{BARE}.txt"), BARE)

    def test_forward_slash_path(self):
        self.assertEqual(
            normalize_directive_arg(f"backtest_directives/INBOX/{BARE}.txt"), BARE
        )

    def test_mr_single_asset_path(self):
        sid = "15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00__E002"
        self.assertEqual(
            normalize_directive_arg(f"backtest_directives/INBOX/{sid}.txt"), sid
        )

    @unittest.skipUnless(os.name == "nt", "Windows backslash path semantics")
    def test_windows_backslash_path(self):
        self.assertEqual(
            normalize_directive_arg(rf"backtest_directives\INBOX\{BARE}.txt"), BARE
        )

    def test_normalized_id_resolves_where_raw_path_did_not(self):
        # End-to-end: the normalized id resolves via find_directive_path; the
        # raw full-path form (pre-fix behaviour) does not.
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "INBOX"
            inbox.mkdir()
            (inbox / f"{BARE}.txt").write_text("test:\n  name: x\n", encoding="utf-8")

            raw_form = f"backtest_directives/INBOX/{BARE}.txt".replace(".txt", "")
            self.assertIsNone(find_directive_path(inbox, raw_form))

            normalized = normalize_directive_arg(f"backtest_directives/INBOX/{BARE}.txt")
            self.assertIsNotNone(find_directive_path(inbox, normalized))


if __name__ == "__main__":
    unittest.main()
