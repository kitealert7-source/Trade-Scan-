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

            data = json.loads(mgr.state_file.read_text(encoding="utf-8"))
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

            data = json.loads(mgr.state_file.read_text(encoding="utf-8"))
            self.assertEqual(data["current_state"], "IDLE")

            # Last history entry must be STAGE_3_COMPLETE -> IDLE
            last = data["history"][-1]
            self.assertEqual(last["from"], "STAGE_3_COMPLETE")
            self.assertEqual(last["to"], "IDLE")


class TestInitializeTerminalStateGuard(unittest.TestCase):
    """Re-initializing a run in a terminal state must raise RuntimeError.

    Regression guard for the 2026-05-18 basket-run-7440e5e7 incident: a
    duplicate basket dispatch silently reset a COMPLETE run back to IDLE,
    then the surrounding try/except transitioned it to FAILED — corrupting
    the state machine and tripping the broader pytest baseline.

    Non-terminal in-progress states (e.g., STAGE_3_COMPLETE) remain
    resettable per TestInitializeResetHistory.
    """

    def _advance_through(self, td, states):
        mgr = _TempStateManager(td)
        mgr.initialize()
        for s in states:
            mgr.transition_to(s)
        return mgr

    def test_initialize_on_complete_raises(self):
        complete_path = [
            "PREFLIGHT_COMPLETE",
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "STAGE_1_COMPLETE",
            "STAGE_2_COMPLETE",
            "STAGE_3_COMPLETE",
            "STAGE_3A_COMPLETE",
            "COMPLETE",
        ]
        with tempfile.TemporaryDirectory() as td:
            mgr = self._advance_through(td, complete_path)
            with self.assertRaises(RuntimeError) as ctx:
                mgr.initialize()
            self.assertIn("COMPLETE", str(ctx.exception))
            # State must be untouched
            data = json.loads(mgr.state_file.read_text(encoding="utf-8"))
            self.assertEqual(data["current_state"], "COMPLETE")

    def test_initialize_on_failed_raises(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()
            mgr.transition_to("FAILED")
            with self.assertRaises(RuntimeError):
                mgr.initialize()
            data = json.loads(mgr.state_file.read_text(encoding="utf-8"))
            self.assertEqual(data["current_state"], "FAILED")

    def test_initialize_on_aborted_raises(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()
            mgr.transition_to("PREFLIGHT_COMPLETE")
            mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            mgr.abort(reason="TEST_ABORT")
            with self.assertRaises(RuntimeError):
                mgr.initialize()
            data = json.loads(mgr.state_file.read_text(encoding="utf-8"))
            self.assertEqual(data["current_state"], "ABORTED")

    def test_history_timestamp_not_double_tagged(self):
        """initialize() reset and abort() must emit ISO timestamps without
        the malformed '+00:00Z' tail (regression for the same incident).
        """
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()
            mgr.transition_to("PREFLIGHT_COMPLETE")
            mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            mgr.transition_to("STAGE_1_COMPLETE")
            mgr.initialize()  # legal reset from STAGE_1_COMPLETE

            data = json.loads(mgr.state_file.read_text(encoding="utf-8"))
            for entry in data.get("history", []):
                ts = entry.get("timestamp", "")
                self.assertFalse(
                    ts.endswith("+00:00Z"),
                    f"malformed timestamp in history: {ts!r}",
                )

    def test_state_reset_appends_audit_event(self):
        """The reset path must call _append_audit_log so STATE_RESET is
        visible to investigators (predecessor only updated history).
        """
        with tempfile.TemporaryDirectory() as td:
            mgr = _TempStateManager(td)
            mgr.initialize()
            mgr.transition_to("PREFLIGHT_COMPLETE")
            mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            mgr.transition_to("STAGE_1_COMPLETE")
            mgr.initialize()  # reset from STAGE_1_COMPLETE

            audit_lines = mgr.audit_log.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line)["event"] for line in audit_lines if line.strip()]
            self.assertIn("STATE_RESET", events)


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
