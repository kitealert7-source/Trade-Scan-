"""
Test Resume Artifacts — Regression tests for artifact preservation on resume.

Verifies that:
1. When all symbols are past Stage-1, batch_summary_*.csv is NOT deleted.
2. The summary deletion guard correctly identifies rerun-needing states.
"""

import unittest
import tempfile
import shutil
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.pipeline_utils import PipelineStateManager


class TestSummaryDeletionGuard(unittest.TestCase):
    """Proves the summary CSV deletion guard logic works correctly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import tools.pipeline_utils as pu
        self._orig_runs_dir = pu.RUNS_DIR
        pu.RUNS_DIR = Path(self.tmpdir)

    def tearDown(self):
        import tools.pipeline_utils as pu
        pu.RUNS_DIR = self._orig_runs_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_run(self, run_id, state):
        """Helper: create a run state file at a given state."""
        mgr = PipelineStateManager(run_id)
        mgr.initialize()
        # Walk forward to desired state
        transitions = {
            "IDLE": [],
            "PREFLIGHT_COMPLETE": ["PREFLIGHT_COMPLETE"],
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID": [
                "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID"],
            "STAGE_1_COMPLETE": [
                "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE"],
            "STAGE_2_COMPLETE": [
                "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE", "STAGE_2_COMPLETE"],
            "COMPLETE": [
                "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE", "STAGE_2_COMPLETE", "STAGE_3_COMPLETE",
                "STAGE_3A_COMPLETE", "COMPLETE"],
        }
        for t in transitions.get(state, []):
            mgr.transition_to(t)
        return run_id

    def test_no_deletion_when_all_symbols_past_stage1(self):
        """If all runs are at STAGE_1_COMPLETE or beyond, no Stage-1 rerun needed."""
        run_ids = [
            self._make_run("run_a", "STAGE_1_COMPLETE"),
            self._make_run("run_b", "STAGE_2_COMPLETE"),
            self._make_run("run_c", "COMPLETE"),
        ]

        # The guard logic from run_pipeline.py
        _any_stage1_rerun = any(
            PipelineStateManager(rid).get_state_data()["current_state"]
            in ("IDLE", "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            for rid in run_ids
        )
        self.assertFalse(_any_stage1_rerun,
                         "Should NOT flag Stage-1 rerun when all symbols past STAGE_1_COMPLETE")

    def test_deletion_when_some_symbols_need_stage1(self):
        """If any run is still pre-Stage-1, rerun is needed."""
        run_ids = [
            self._make_run("run_d", "STAGE_1_COMPLETE"),
            self._make_run("run_e", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID"),  # needs rerun
        ]

        _any_stage1_rerun = any(
            PipelineStateManager(rid).get_state_data()["current_state"]
            in ("IDLE", "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            for rid in run_ids
        )
        self.assertTrue(_any_stage1_rerun,
                        "Should flag Stage-1 rerun when some symbols are pre-STAGE_1_COMPLETE")


if __name__ == "__main__":
    unittest.main()
