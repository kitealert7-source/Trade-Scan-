"""Integration test for --provision-only end-to-end behavior."""

import sys
import json
import uuid
import unittest
import shutil
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestProvisionOnlyIntegration(unittest.TestCase):
    def setUp(self):
        self.d_id = f"TEST_PROVISION_{uuid.uuid4().hex[:8].upper()}"
        self.d_path = PROJECT_ROOT / "backtest_directives" / "active" / f"{self.d_id}.txt"
        self.strat_dir = PROJECT_ROOT / "strategies" / self.d_id

        # Build canonical directive
        content = '''test:
  name: __DID__
  family: Index
  strategy: __DID__
  broker: OctaFx
  timeframe: 1d
  session_time_reference: UTC
  start_date: 2015-01-01
  end_date: 2026-01-31
  research_mode: false
  tuning_allowed: false
  parameter_mutation: false
  description: Test directive

symbols:
  - EURUSD

indicators:
  - indicators.structure.highest_high

execution_rules:
  pyramiding: false
  entry_when_flat_only: true
  reset_on_exit: true
  entry_logic:
    type: volatility_pullback
  exit_logic:
    type: dynamic_or_time
  stop_loss:
    type: none
'''.replace("__DID__", self.d_id)

        self.d_path.write_text(content, encoding="utf-8")
        if self.strat_dir.exists():
            shutil.rmtree(self.strat_dir, ignore_errors=True)
        self.strat_dir.mkdir(parents=True, exist_ok=True)

        strat_content = '''from tools.pipeline_utils import FilterStack

# Auto-generated strategy stub
class Strategy:
    name = "__DID__"
    timeframe = "1d"

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {}
    # --- STRATEGY SIGNATURE END ---

    def __init__(self):
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)

    # --- START USER CODE ---
    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None
        return {"signal": 1}

    def check_exit(self, ctx):
        return {"signal": -1}
    # --- END USER CODE ---
'''.replace("__DID__", self.d_id)

        (self.strat_dir / "strategy.py").write_text(strat_content, encoding="utf-8")

    def _cleanup_run_artifacts(self):
        runs_dir = PROJECT_ROOT / "runs"

        # Directive-level state directory
        shutil.rmtree(runs_dir / self.d_id, ignore_errors=True)

        # Symbol run directories linked to this directive id
        if runs_dir.exists():
            for run_dir in runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                state_file = run_dir / "run_state.json"
                if not state_file.exists():
                    continue
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if state.get("directive_id") == self.d_id:
                    shutil.rmtree(run_dir, ignore_errors=True)

    def tearDown(self):
        if self.d_path.exists():
            self.d_path.unlink()
        if self.strat_dir.exists():
            shutil.rmtree(self.strat_dir, ignore_errors=True)
        self._cleanup_run_artifacts()

    def test_run_pipeline_provision_only(self):
        res = subprocess.run(
            [
                sys.executable,
                "tools/run_pipeline.py",
                self.d_id,
                "--provision-only",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            res.returncode,
            0,
            f"Provision only failed: {res.stderr}\n\nSTDOUT:\n{res.stdout}",
        )
        self.assertIn("[PROVISION-ONLY] Strategy provisioned at:", res.stdout)
        self.assertIn("[PROVISION-ONLY] Human review required before execution.", res.stdout)
        self.assertIn("[PROVISION-ONLY] Re-run without --provision-only after review.", res.stdout)
        self.assertNotIn("Launching Stage-1 Generator (Atomic)...", res.stdout)
        self.assertNotIn("Stage-1: EURUSD", res.stdout)

        strat_file = self.strat_dir / "strategy.py"
        self.assertTrue(strat_file.exists(), "Strategy file was not provisioned")

        from tools.pipeline_utils import DirectiveStateManager, PipelineStateManager, generate_run_id

        state = DirectiveStateManager(self.d_id).get_state()
        self.assertEqual(
            state,
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "Unexpected state after --provision-only",
        )

        run_id, _ = generate_run_id(self.d_path, "EURUSD")
        run_state = PipelineStateManager(run_id).get_state_data().get("current_state")
        self.assertEqual(
            run_state,
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "Unexpected symbol run state after --provision-only",
        )


if __name__ == "__main__":
    unittest.main()
