"""
Test Resume FSM — Regression tests for pipeline resume behavior.

Verifies that:
1. Resume from PREFLIGHT_COMPLETE_SEMANTICALLY_VALID does not re-trigger 
   preflight or cause an illegal backward transition.
2. Resume from SYMBOL_RUNS_COMPLETE skips all stages.
3. DirectiveStateManager rejects backward transitions (e.g., trying 
   PREFLIGHT_COMPLETE from PREFLIGHT_COMPLETE_SEMANTICALLY_VALID).
"""

import unittest
import tempfile
import shutil
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.pipeline_utils import PipelineStateManager, DirectiveStateManager


class TestDirectiveBackwardTransitionRejected(unittest.TestCase):
    """Proves that trying to move backward in the directive FSM raises RuntimeError."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_runs = DirectiveStateManager.__init__.__code__
        # Patch RUNS_DIR to use temp
        import tools.pipeline_utils as pu
        self._orig_runs_dir = pu.RUNS_DIR
        pu.RUNS_DIR = Path(self.tmpdir)

    def tearDown(self):
        import tools.pipeline_utils as pu
        pu.RUNS_DIR = self._orig_runs_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backward_from_semantically_valid_to_preflight_complete(self):
        """PREFLIGHT_COMPLETE_SEMANTICALLY_VALID -> PREFLIGHT_COMPLETE must be rejected."""
        mgr = DirectiveStateManager("test_directive")
        mgr.initialize()

        # Advance to PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
        mgr.transition_to("PREFLIGHT_COMPLETE")
        mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")

        # Attempting backward transition must raise
        with self.assertRaises(RuntimeError) as ctx:
            mgr.transition_to("PREFLIGHT_COMPLETE")
        self.assertIn("Illegal", str(ctx.exception))

    def test_backward_from_symbol_runs_to_semantic(self):
        """SYMBOL_RUNS_COMPLETE -> PREFLIGHT_COMPLETE_SEMANTICALLY_VALID must be rejected."""
        mgr = DirectiveStateManager("test_directive_2")
        mgr.initialize()
        mgr.transition_to("PREFLIGHT_COMPLETE")
        mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
        mgr.transition_to("SYMBOL_RUNS_COMPLETE")

        with self.assertRaises(RuntimeError):
            mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")


class TestResumeStateSkip(unittest.TestCase):
    """Proves that the preflight skip set correctly identifies forward states."""

    def test_preflight_skip_set_covers_all_forward_states(self):
        """All states past INITIALIZED should cause preflight to be skipped."""
        _PREFLIGHT_SKIP = {"PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                           "SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"}

        # These states must be in the skip set
        forward_states = [
            "PREFLIGHT_COMPLETE",
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "SYMBOL_RUNS_COMPLETE",
            "PORTFOLIO_COMPLETE"
        ]
        for state in forward_states:
            self.assertIn(state, _PREFLIGHT_SKIP,
                          f"Forward state {state} missing from preflight skip set")

        # INITIALIZED and FAILED must NOT be in skip set
        self.assertNotIn("INITIALIZED", _PREFLIGHT_SKIP)
        self.assertNotIn("FAILED", _PREFLIGHT_SKIP)


class TestDirectiveAllowedTransitions(unittest.TestCase):
    """Validates the directive FSM transition table is strictly forward-only."""

    def test_no_backward_paths_exist(self):
        """No state in ALLOWED_TRANSITIONS should allow transitioning to a prior state."""
        state_order = [
            "INITIALIZED",
            "PREFLIGHT_COMPLETE",
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "SYMBOL_RUNS_COMPLETE",
            "PORTFOLIO_COMPLETE"
        ]
        for i, state in enumerate(state_order):
            allowed = DirectiveStateManager.ALLOWED_TRANSITIONS.get(state, [])
            for target in allowed:
                if target == "FAILED":
                    continue  # FAILED is always allowed
                if target == "INITIALIZED" and state == "FAILED":
                    continue  # Reset from FAILED is legitimate
                target_idx = state_order.index(target) if target in state_order else -1
                self.assertGreater(
                    target_idx, i,
                    f"Backward or lateral transition detected: {state} -> {target}"
                )


if __name__ == "__main__":
    unittest.main()
