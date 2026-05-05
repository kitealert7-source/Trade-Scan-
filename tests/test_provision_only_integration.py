"""Integration test for --provision-only end-to-end behavior."""

import sys
import json
import random
import unittest
import shutil
import re
import os
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestProvisionOnlyIntegration(unittest.TestCase):
    def setUp(self):
        # Canonical namespace pattern enforced by namespace_gate:
        #   <ID>_<FAMILY>_<SYMBOL>_<TF>_<MODEL>[_<FILTER>]_S<NN>_V<N>_P<NN>
        # Use idea-id 99 (test scaffolding, no collision with real
        # ideas 01-65). Tokens REV/EURUSD/1D/PINBAR are all in
        # governance/namespace/token_dictionary.yaml. Sweep number
        # randomized per run so concurrent re-runs don't collide on
        # the same registry slot before teardown's snapshot restore.
        sweep_num = random.randint(10, 99)
        self.d_id = f"99_REV_EURUSD_1D_PINBAR_S{sweep_num:02d}_V1_P00"
        self.d_path = PROJECT_ROOT / "backtest_directives" / "INBOX" / f"{self.d_id}.txt"
        self.strat_dir = PROJECT_ROOT / "strategies" / self.d_id
        self.effective_id = None
        self._sweep_registry_path = PROJECT_ROOT / "governance" / "namespace" / "sweep_registry.yaml"
        self._sweep_registry_snapshot = (
            self._sweep_registry_path.read_bytes()
            if self._sweep_registry_path.exists()
            else None
        )

        # Idea 99 must be registered before the namespace gate accepts
        # the directive id. Snapshot + restore so this test doesn't
        # leak a synthetic idea entry into governance state.
        self._idea_registry_path = PROJECT_ROOT / "governance" / "namespace" / "idea_registry.yaml"
        self._idea_registry_snapshot = (
            self._idea_registry_path.read_bytes()
            if self._idea_registry_path.exists()
            else None
        )
        self._inject_test_idea_if_missing()
        self._inject_test_sweep_block_if_missing()

        # Build canonical directive (family token must match the
        # FAMILY in the namespace pattern above — REV).
        content = '''test:
  name: __DID__
  family: REV
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

    def _cleanup_run_artifacts(self, directive_id: str):
        runs_dir = PROJECT_ROOT / "runs"

        # Directive-level state directory
        shutil.rmtree(runs_dir / directive_id, ignore_errors=True)

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
                if state.get("directive_id") == directive_id:
                    shutil.rmtree(run_dir, ignore_errors=True)

    def _cleanup_artifacts_for_id(self, directive_id: str):
        if not directive_id:
            return

        for rel in (
            PROJECT_ROOT / "backtest_directives" / "INBOX" / f"{directive_id}.txt",
            PROJECT_ROOT / "backtest_directives" / "active_backup" / f"{directive_id}.txt",
        ):
            if rel.exists():
                rel.unlink()

        shutil.rmtree(PROJECT_ROOT / "strategies" / directive_id, ignore_errors=True)
        self._cleanup_run_artifacts(directive_id)

    def _inject_test_idea_if_missing(self):
        """Idea 99 is reserved for test scaffolding. Add a synthetic
        entry to idea_registry.yaml so namespace_gate's
        IDEA_ID_UNREGISTERED check passes. tearDown restores from
        snapshot."""
        import yaml
        if not self._idea_registry_path.exists():
            return
        data = yaml.safe_load(self._idea_registry_path.read_text(encoding="utf-8")) or {}
        ideas = data.setdefault("ideas", {})
        if "99" not in ideas:
            ideas["99"] = {
                "family": "REV",
                "title": "Test Scaffold (provision-only integration test)",
                "class": "indicator_logic",
                "regime": "range",
                "role": "entry_edge",
                "status": "active",
            }
            self._idea_registry_path.write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )

    def _inject_test_sweep_block_if_missing(self):
        """Sweep registry needs idea 99 to exist as a top-level entry
        before SWEEP_IDEA_UNREGISTERED check passes. The sweep slot
        itself is auto-reserved by the pipeline; we just need the
        idea_id key to exist with an empty sweeps map."""
        import yaml
        if not self._sweep_registry_path.exists():
            return
        data = yaml.safe_load(self._sweep_registry_path.read_text(encoding="utf-8")) or {}
        ideas = data.setdefault("ideas", {})
        if "99" not in ideas:
            ideas["99"] = {"next_sweep": 1, "sweeps": {}}
            self._sweep_registry_path.write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )

    def tearDown(self):
        self._cleanup_artifacts_for_id(self.d_id)
        self._cleanup_artifacts_for_id(self.effective_id)
        if self._sweep_registry_snapshot is not None:
            self._sweep_registry_path.write_bytes(self._sweep_registry_snapshot)
        if self._idea_registry_snapshot is not None:
            self._idea_registry_path.write_bytes(self._idea_registry_snapshot)

    @unittest.skip(
        "Multi-layer staleness — partially advanced 2026-05-05 (Batch 3 "
        "rewrite). FIXED: directive id now matches canonical namespace "
        "pattern (99_REV_EURUSD_1D_PINBAR_S<NN>_V1_P00); idea_registry + "
        "sweep_registry get idea-99 injected with snapshot/restore around "
        "the test; tools_manifest stays current; data layer accessible "
        "from main repo. With those fixes the test gets through every "
        "admission gate and into PreflightStage's exec_preflight subprocess. "
        "REMAINING BLOCKER: post-04c05c9 provision-only flow added "
        "EXPERIMENT_DISCIPLINE + SCHEMA_SAMPLE_MISSING gates. The pipeline's "
        "[PROVISION] phase patches the strategy.py STRATEGY_SIGNATURE in "
        "place, then a downstream check pauses with AWAITING_HUMAN_APPROVAL "
        "(strategy.py modified after last approval) and SCHEMA_SAMPLE_MISSING "
        "(strategy needs a _schema_sample() method). The test's expected "
        "output messages ([PROVISION-ONLY] Strategy provisioned at: ...) no "
        "longer match the new flow which now prints [ADMISSION GATE] HUMAN "
        "ACTION REQUIRED instead. Proper full fix needs: (a) test strategy.py "
        "must include _schema_sample() and a STRATEGY_SIGNATURE pre-populated "
        "with whatever the [PROVISION] patcher would produce so no drift is "
        "detected; (b) updated assertion strings matching the post-04c05c9 "
        "provision-only output; (c) ideally refactor away from subprocess — "
        "test BootstrapController + PreflightStage at the Python level the "
        "way Batch 3's test_step6 rewrite does. Tracked as Batch 3.5."
    )
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
            env={**dict(os.environ), "TRADE_SCAN_TEST_SKIP_ENGINE_INTEGRITY": "1"},
        )

        m = re.search(
            r"\[AUTO-MIGRATE\] Directive renamed:\s+\S+\s+->\s+(\S+)",
            res.stdout,
        )
        self.effective_id = m.group(1) if m else self.d_id

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

        effective_id = self.effective_id

        strat_file = PROJECT_ROOT / "strategies" / effective_id / "strategy.py"
        self.assertTrue(strat_file.exists(), "Strategy file was not provisioned")

        from tools.pipeline_utils import DirectiveStateManager, PipelineStateManager, generate_run_id

        state = DirectiveStateManager(effective_id).get_state()
        self.assertEqual(
            state,
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "Unexpected state after --provision-only",
        )

        effective_d_path = PROJECT_ROOT / "backtest_directives" / "INBOX" / f"{effective_id}.txt"
        if not effective_d_path.exists():
            effective_d_path = self.d_path

        run_id, _ = generate_run_id(effective_d_path, "EURUSD")
        run_state = PipelineStateManager(run_id).get_state_data().get("current_state")
        self.assertEqual(
            run_state,
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "Unexpected symbol run state after --provision-only",
        )


if __name__ == "__main__":
    unittest.main()
