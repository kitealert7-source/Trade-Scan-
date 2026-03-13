"""Tests for centralized pipeline error mapping behavior."""

import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.orchestration.pipeline_errors import (
    PipelineAdmissionPause,
    PipelineExecutionError,
)
from tools.run_pipeline import map_pipeline_error


class TestPipelineErrorMapper(unittest.TestCase):
    def test_admission_pause_returns_zero_without_cleanup(self):
        err = PipelineAdmissionPause("pause for manual intervention", directive_id="D1", run_ids=["R1"])
        with patch("tools.run_pipeline.fail_directive_best_effort") as fail_dir, patch(
            "tools.run_pipeline.fail_run_best_effort"
        ) as fail_run:
            code = map_pipeline_error(err)

        self.assertEqual(code, 0)
        fail_dir.assert_not_called()
        fail_run.assert_not_called()

    def test_execution_error_triggers_directive_and_run_cleanup(self):
        err = PipelineExecutionError("fatal failure", directive_id="D2", run_ids=["R2", "R3"])
        with patch("tools.run_pipeline.fail_directive_best_effort") as fail_dir, patch(
            "tools.run_pipeline.fail_run_best_effort", return_value=True
        ) as fail_run:
            code = map_pipeline_error(err)

        self.assertEqual(code, 1)
        fail_dir.assert_called_once_with("D2")
        self.assertEqual(fail_run.call_count, 2)
        fail_run.assert_any_call("R2")
        fail_run.assert_any_call("R3")

    def test_execution_error_respects_cleanup_flags(self):
        err = PipelineExecutionError(
            "non-cleanup failure",
            directive_id="D3",
            run_ids=["R4"],
            fail_directive=False,
            fail_runs=False,
        )
        with patch("tools.run_pipeline.fail_directive_best_effort") as fail_dir, patch(
            "tools.run_pipeline.fail_run_best_effort"
        ) as fail_run:
            code = map_pipeline_error(err)

        self.assertEqual(code, 1)
        fail_dir.assert_not_called()
        fail_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
