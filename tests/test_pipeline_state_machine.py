"""
FSM Invariant Tests for PipelineStateManager.

Tests the state machine contract defined in pipeline_utils.py.
Uses only unittest and tempfile -- no external frameworks.
"""
import sys
import json
import unittest
import tempfile
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import PipelineStateManager


class _TempStateManager(PipelineStateManager):
    """Helper that redirects state files to a temp directory."""

    def __init__(self, tmp_dir, run_id="test_run"):
        self.run_id = run_id
        self.directive_id = None
        self.run_dir = Path(tmp_dir) / run_id
        self.state_file = self.run_dir / "run_state.json"
        self.audit_log = self.run_dir / "audit.log"


class TestValidForwardTransition(unittest.TestCase):
    """Test 1 -- A full legal forward path completes without error."""

    def test_full_legal_path(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()

            legal_path = [
                "PREFLIGHT_COMPLETE",
                "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE",
                "STAGE_2_COMPLETE",
                "STAGE_3_COMPLETE",
                "STAGE_3A_COMPLETE",
                "COMPLETE",
            ]

            for state in legal_path:
                mgr.transition_to(state)

            data = json.loads(mgr.state_file.read_text())
            self.assertEqual(data["current_state"], "COMPLETE")
            self.assertEqual(len(data["history"]), len(legal_path))


class TestIllegalBackwardTransition(unittest.TestCase):
    """Test 2 -- Backward transition raises RuntimeError."""

    def test_backward_transition_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()
            mgr.transition_to("PREFLIGHT_COMPLETE")
            mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            mgr.transition_to("STAGE_1_COMPLETE")

            with self.assertRaises(RuntimeError):
                mgr.transition_to("PREFLIGHT_COMPLETE")


class TestInitializeResetHistory(unittest.TestCase):
    """Test 3 -- initialize() records true prior state, not IDLE -> IDLE."""

    def test_reset_logs_correct_prior_state(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()

            # Advance to STAGE_3_COMPLETE
            for s in [
                "PREFLIGHT_COMPLETE",
                "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                "STAGE_1_COMPLETE",
                "STAGE_2_COMPLETE",
                "STAGE_3_COMPLETE",
            ]:
                mgr.transition_to(s)

            # Re-initialize (reset to IDLE)
            mgr.initialize()

            data = json.loads(mgr.state_file.read_text())
            self.assertEqual(data["current_state"], "IDLE")

            # Last history entry must be STAGE_3_COMPLETE -> IDLE
            last = data["history"][-1]
            self.assertEqual(last["from"], "STAGE_3_COMPLETE")
            self.assertEqual(last["to"], "IDLE")


class TestVerifyStateRaisesRuntimeError(unittest.TestCase):
    """Test 4 -- verify_state() raises RuntimeError, never SystemExit."""

    def test_state_mismatch_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()  # state = IDLE

            with self.assertRaises(RuntimeError):
                mgr.verify_state("PREFLIGHT_COMPLETE")

    def test_no_system_exit_on_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()

            try:
                mgr.verify_state("PREFLIGHT_COMPLETE")
                self.fail("Expected RuntimeError was not raised")
            except RuntimeError:
                pass  # correct
            except SystemExit:
                self.fail("SystemExit raised instead of RuntimeError")

    def test_missing_state_file_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            # Do NOT initialize -- state file does not exist

            with self.assertRaises(RuntimeError):
                mgr.verify_state("IDLE")


if __name__ == "__main__":
    unittest.main()
