import shutil
import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.pipeline_utils as pu
from tools.orchestration.transition_service import (
    fail_directive_best_effort,
    fail_run_best_effort,
    fail_runs_best_effort,
    get_directive_state,
    get_run_state,
    transition_directive_state,
    transition_run_state,
    transition_run_state_sequence,
    transition_run_states_if,
)
from tools.pipeline_utils import DirectiveStateManager, PipelineStateManager


class TestTransitionService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_runs_dir = pu.RUNS_DIR
        pu.RUNS_DIR = Path(self.tmpdir)

    def tearDown(self):
        pu.RUNS_DIR = self._orig_runs_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_transition_run_states_if_only_moves_allowed_current_state(self):
        r1 = PipelineStateManager("run_idle", directive_id="D1")
        r2 = PipelineStateManager("run_preflight", directive_id="D1")
        r1.initialize()
        r2.initialize()
        r2.transition_to("PREFLIGHT_COMPLETE")

        moved = transition_run_states_if(
            ["run_idle", "run_preflight"],
            "PREFLIGHT_COMPLETE",
            {"IDLE"},
        )

        self.assertEqual(moved, ["run_idle"])
        self.assertEqual(get_run_state("run_idle"), "PREFLIGHT_COMPLETE")
        self.assertEqual(get_run_state("run_preflight"), "PREFLIGHT_COMPLETE")

    def test_transition_run_state_sequence(self):
        run_id = "run_seq"
        mgr = PipelineStateManager(run_id, directive_id="D2")
        mgr.initialize()

        transition_run_state_sequence(
            run_id,
            [
                "PREFLIGHT_COMPLETE",
                "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE",
            ],
        )

        self.assertEqual(get_run_state(run_id), "STAGE_1_COMPLETE")

    def test_fail_runs_best_effort_skips_terminal_and_missing(self):
        run_open = "run_open"
        run_complete = "run_complete"
        PipelineStateManager(run_open, directive_id="D3").initialize()
        PipelineStateManager(run_complete, directive_id="D3").initialize()

        transition_run_state_sequence(
            run_complete,
            [
                "PREFLIGHT_COMPLETE",
                "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE",
                "STAGE_2_COMPLETE",
                "STAGE_3_COMPLETE",
                "STAGE_3A_COMPLETE",
                "COMPLETE",
            ],
        )

        moved = fail_runs_best_effort([run_open, run_complete, "missing_run"])

        self.assertEqual(moved, ["run_open"])
        self.assertEqual(get_run_state(run_open), "FAILED")
        self.assertEqual(get_run_state(run_complete), "COMPLETE")
        self.assertFalse(fail_run_best_effort("missing_run"))

    def test_directive_failed_and_reset_via_service(self):
        directive_id = "D4"
        d_mgr = DirectiveStateManager(directive_id)
        d_mgr.initialize()
        transition_directive_state(directive_id, "PREFLIGHT_COMPLETE")

        changed = fail_directive_best_effort(directive_id)
        self.assertTrue(changed)
        self.assertEqual(get_directive_state(directive_id), "FAILED")

        transition_directive_state(directive_id, "INITIALIZED")
        self.assertEqual(get_directive_state(directive_id), "INITIALIZED")


if __name__ == "__main__":
    unittest.main()
