"""Tests for run planner and persistent run registry behavior."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.orchestration.run_planner import plan_runs_for_directive
from tools.orchestration.run_registry import (
    claim_next_planned_run,
    list_runs,
    requeue_running_runs,
    update_run_state,
)


def _directive_file(path: Path, directive_id: str) -> Path:
    p = path / f"{directive_id}.txt"
    p.write_text(
        f"""test:
  name: {directive_id}
symbols:
  - EURUSD
  - USDJPY
""",
        encoding="utf-8",
    )
    return p


class TestRunPlannerRegistry(unittest.TestCase):
    def test_plan_runs_writes_registry_and_preserves_existing_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directive_id = "PLAN_CASE"
            dpath = _directive_file(root, directive_id)

            planned, reg_path = plan_runs_for_directive(
                directive_id=directive_id,
                directive_path=dpath,
                strategy_id=directive_id,
                symbols=["EURUSD", "USDJPY"],
                project_root=root,
            )
            self.assertEqual(len(planned), 2)
            self.assertTrue(reg_path.exists())

            runs = list_runs(reg_path, directive_id)
            self.assertEqual([r["state"] for r in runs], ["PLANNED", "PLANNED"])

            update_run_state(reg_path, directive_id, runs[0]["run_id"], "RUNNING")
            update_run_state(reg_path, directive_id, runs[0]["run_id"], "COMPLETE")

            planned2, _ = plan_runs_for_directive(
                directive_id=directive_id,
                directive_path=dpath,
                strategy_id=directive_id,
                symbols=["EURUSD", "USDJPY"],
                project_root=root,
            )
            self.assertEqual(len(planned2), 2)

            runs2 = list_runs(reg_path, directive_id)
            self.assertEqual(runs2[0]["state"], "COMPLETE")
            self.assertEqual(runs2[1]["state"], "PLANNED")

    def test_claim_and_requeue_support_resume_after_interrupt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directive_id = "REQUEUE_CASE"
            dpath = _directive_file(root, directive_id)

            _, reg_path = plan_runs_for_directive(
                directive_id=directive_id,
                directive_path=dpath,
                strategy_id=directive_id,
                symbols=["EURUSD"],
                project_root=root,
            )

            claim = claim_next_planned_run(reg_path, directive_id)
            self.assertIsNotNone(claim)
            self.assertEqual(claim["state"], "RUNNING")

            self.assertEqual(requeue_running_runs(reg_path, directive_id), 1)
            runs = list_runs(reg_path, directive_id)
            self.assertEqual(runs[0]["state"], "PLANNED")

            claim2 = claim_next_planned_run(reg_path, directive_id)
            self.assertIsNotNone(claim2)
            self.assertEqual(claim2["state"], "RUNNING")

            update_run_state(reg_path, directive_id, claim2["run_id"], "FAILED", last_error="boom")
            runs2 = list_runs(reg_path, directive_id)
            self.assertEqual(runs2[0]["state"], "FAILED")
            self.assertEqual(runs2[0]["last_error"], "boom")

    def test_registry_is_persistent_on_disk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directive_id = "DISK_CASE"
            dpath = _directive_file(root, directive_id)

            _, reg_path = plan_runs_for_directive(
                directive_id=directive_id,
                directive_path=dpath,
                strategy_id=directive_id,
                symbols=["EURUSD", "USDJPY"],
                project_root=root,
            )

            with open(reg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["directive_id"], directive_id)
            self.assertEqual(len(data["runs"]), 2)
            self.assertIn("updated_at", data)


if __name__ == "__main__":
    unittest.main()
