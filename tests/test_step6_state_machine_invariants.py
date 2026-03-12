"""Step 6 invariant hardening tests for pipeline orchestration."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.orchestration.pipeline_errors import PipelineExecutionError
from tools.orchestration.stage_preflight import run_preflight_semantic_checks
from tools.orchestration.stage_symbol_execution import run_symbol_execution_stages
from tools.run_pipeline import map_pipeline_error, run_single_directive


def _directive_yaml(directive_id: str, symbols: list[str]) -> str:
    symbol_lines = "\n".join(f"  - {s}" for s in symbols)
    return f"""test:
  name: {directive_id}
symbols:
{symbol_lines}
"""


class _SeqDirectiveState:
    def __init__(self, states: list[str]):
        self._states = list(states)
        self._last = states[-1]

    def initialize(self):
        return None

    def get_state(self):
        if self._states:
            self._last = self._states.pop(0)
        return self._last


class TestRunPipelineScenarioInvariants(unittest.TestCase):
    def _write_directive(self, td: str, directive_id: str, symbols: list[str]) -> Path:
        p = Path(td) / f"{directive_id}.txt"
        p.write_text(_directive_yaml(directive_id, symbols), encoding="utf-8")
        return p

    def test_resume_skips_preflight_and_symbol_stages(self):
        with tempfile.TemporaryDirectory() as td:
            did = "RESUME_CASE"
            dpath = self._write_directive(td, did, ["EURUSD", "USDJPY"])
            d_mgr = _SeqDirectiveState(["SYMBOL_RUNS_COMPLETE", "SYMBOL_RUNS_COMPLETE"])

            with patch("tools.run_pipeline.get_directive_path", return_value=dpath), patch(
                "tools.canonicalizer.canonicalize",
                return_value=({}, "canonical", [], [], False),
            ), patch(
                "tools.namespace_gate.validate_namespace",
                return_value={
                    "strategy_name": did,
                    "idea_id": "ID01",
                    "family": "Index",
                    "model": "MR",
                    "filter": None,
                },
            ), patch(
                "tools.sweep_registry_gate.reserve_sweep",
                return_value={"status": "existing", "idea_id": "ID01", "sweep": "P00"},
            ), patch(
                "tools.pipeline_utils.parse_directive",
                return_value={"Symbols": ["EURUSD", "USDJPY"], "Strategy": did},
            ), patch(
                "tools.run_pipeline.DirectiveStateManager",
                return_value=d_mgr,
            ), patch(
                "tools.run_pipeline.plan_runs_for_directive",
                return_value=(
                    [
                        {"run_id": "RID_EURUSD", "strategy": did, "symbol": "EURUSD"},
                        {"run_id": "RID_USDJPY", "strategy": did, "symbol": "USDJPY"},
                    ],
                    Path(td) / "runs" / did / "run_registry.json",
                ),
            ), patch(
                "tools.run_pipeline.run_preflight_semantic_checks"
            ) as preflight_mock, patch(
                "tools.run_pipeline.run_symbol_execution_stages"
            ) as symbol_mock, patch(
                "tools.run_pipeline.run_portfolio_and_post_stages"
            ) as portfolio_mock:
                run_single_directive(did, provision_only=False)

        preflight_mock.assert_not_called()
        symbol_mock.assert_not_called()
        portfolio_mock.assert_called_once()
        self.assertEqual(
            portfolio_mock.call_args.kwargs["run_ids"],
            ["RID_EURUSD", "RID_USDJPY"],
        )

    def test_provision_only_rerun_resets_failed_directive(self):
        with tempfile.TemporaryDirectory() as td:
            did = "PROVISION_RESET_CASE"
            dpath = self._write_directive(td, did, ["EURUSD"])
            d_mgr = _SeqDirectiveState(["FAILED", "INITIALIZED", "INITIALIZED"])

            with patch("tools.run_pipeline.get_directive_path", return_value=dpath), patch(
                "tools.canonicalizer.canonicalize",
                return_value=({}, "canonical", [], [], False),
            ), patch(
                "tools.namespace_gate.validate_namespace",
                return_value={
                    "strategy_name": did,
                    "idea_id": "ID02",
                    "family": "Index",
                    "model": "MR",
                    "filter": None,
                },
            ), patch(
                "tools.sweep_registry_gate.reserve_sweep",
                return_value={"status": "existing", "idea_id": "ID02", "sweep": "P00"},
            ), patch(
                "tools.pipeline_utils.parse_directive",
                return_value={"Symbols": ["EURUSD"], "Strategy": did},
            ), patch(
                "tools.run_pipeline.DirectiveStateManager",
                return_value=d_mgr,
            ), patch(
                "tools.run_pipeline.PipelineStateManager"
            ) as psm_mock, patch(
                "tools.run_pipeline.transition_directive_state"
            ) as transition_mock, patch(
                "tools.run_pipeline.plan_runs_for_directive",
                return_value=(
                    [{"run_id": "RID_EURUSD", "strategy": did, "symbol": "EURUSD"}],
                    Path(td) / "runs" / did / "run_registry.json",
                ),
            ), patch(
                "tools.run_pipeline.run_preflight_semantic_checks",
                return_value=True,
            ) as preflight_mock, patch(
                "tools.run_pipeline.run_symbol_execution_stages"
            ) as symbol_mock, patch(
                "tools.run_pipeline.run_portfolio_and_post_stages"
            ) as portfolio_mock:
                run_single_directive(did, provision_only=True)

        transition_mock.assert_called_once_with(did, "INITIALIZED")
        preflight_mock.assert_called_once()
        symbol_mock.assert_not_called()
        portfolio_mock.assert_not_called()
        self.assertEqual(psm_mock.return_value.initialize.call_count, 1)

    def test_failed_directive_without_provision_requires_manual_reset(self):
        with tempfile.TemporaryDirectory() as td:
            did = "FAILED_NO_PROVISION"
            dpath = self._write_directive(td, did, ["EURUSD"])
            d_mgr = _SeqDirectiveState(["FAILED"])

            with patch("tools.run_pipeline.get_directive_path", return_value=dpath), patch(
                "tools.canonicalizer.canonicalize",
                return_value=({}, "canonical", [], [], False),
            ), patch(
                "tools.namespace_gate.validate_namespace",
                return_value={
                    "strategy_name": did,
                    "idea_id": "ID03",
                    "family": "Index",
                    "model": "MR",
                    "filter": None,
                },
            ), patch(
                "tools.sweep_registry_gate.reserve_sweep",
                return_value={"status": "existing", "idea_id": "ID03", "sweep": "P00"},
            ), patch(
                "tools.pipeline_utils.parse_directive",
                return_value={"Symbols": ["EURUSD"], "Strategy": did},
            ), patch(
                "tools.run_pipeline.DirectiveStateManager",
                return_value=d_mgr,
            ), patch("tools.run_pipeline.transition_directive_state") as transition_mock:
                with self.assertRaises(PipelineExecutionError) as ctx:
                    run_single_directive(did, provision_only=False)

        self.assertIn("must be reset", str(ctx.exception))
        transition_mock.assert_not_called()


class TestMultiSymbolPartialFailureInvariant(unittest.TestCase):
    def test_stage1_partial_failure_marks_only_failing_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "backtests" / "CASE_EURUSD" / "raw").mkdir(parents=True, exist_ok=True)
            (root / "backtests" / "CASE_EURUSD" / "raw" / "results_tradelevel.csv").write_text(
                "x\n1\n",
                encoding="utf-8",
            )
            runs_root = root / "runs"

            class FakeManager:
                def __init__(self, run_id):
                    self.run_id = run_id
                    self.run_dir = runs_root / run_id
                    self.run_dir.mkdir(parents=True, exist_ok=True)

                def get_state_data(self):
                    return {"current_state": "IDLE"}

                def _append_audit_log(self, *_args, **_kwargs):
                    return None

            run_cmd = Mock()
            with patch(
                "tools.orchestration.stage_symbol_execution.PipelineStateManager",
                side_effect=lambda rid: FakeManager(rid),
            ), patch(
                "tools.skill_loader.run_skill",
                side_effect=[None, RuntimeError("stage1 boom")],
            ), patch(
                "tools.orchestration.stage_symbol_execution.transition_run_state"
            ) as trs_mock:
                with self.assertRaises(RuntimeError) as ctx:
                    run_symbol_execution_stages(
                        clean_id="CASE",
                        p_conf={"Strategy": "CASE"},
                        run_ids=["RID1", "RID2"],
                        symbols=["EURUSD", "USDJPY"],
                        project_root=root,
                        python_exe="python",
                        run_command=run_cmd,
                    )

        self.assertIn("stage1 boom", str(ctx.exception))
        trs_mock.assert_has_calls(
            [
                call("RID1", "STAGE_1_COMPLETE"),
                call("RID2", "FAILED"),
            ],
            any_order=False,
        )
        run_cmd.assert_not_called()


class TestGoldenOutputStability(unittest.TestCase):
    def test_provision_only_output_golden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d_path = root / "directive.txt"
            d_path.write_text(_directive_yaml("GOLDEN", ["EURUSD"]), encoding="utf-8")

            mgr = _SeqDirectiveState(
                [
                    "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                    "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                    "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                ]
            )
            out = io.StringIO()
            with redirect_stdout(out):
                should_stop = run_preflight_semantic_checks(
                    clean_id="GOLDEN",
                    d_path=d_path,
                    p_conf={"Strategy": "GOLDEN"},
                    run_ids=["RID1"],
                    symbols=["EURUSD"],
                    dir_state_mgr=mgr,
                    provision_only=True,
                    project_root=root,
                    python_exe="python",
                    run_command=Mock(),
                )

        self.assertTrue(should_stop)
        strategy_path = root / "strategies" / "GOLDEN" / "strategy.py"
        expected = [
            "[ORCHESTRATOR] Preflight already complete (state=PREFLIGHT_COMPLETE_SEMANTICALLY_VALID). Checking Semantic Status...",
            "[ORCHESTRATOR] Semantic Validation already COMPLETE. Resuming...",
            f"[PROVISION-ONLY] Strategy provisioned at: {strategy_path}",
            "[PROVISION-ONLY] Human review required before execution.",
            "[PROVISION-ONLY] Re-run without --provision-only after review.",
        ]
        self.assertEqual(out.getvalue().strip().splitlines(), expected)

    def test_error_mapper_output_golden(self):
        out = io.StringIO()
        err = PipelineExecutionError("fatal", directive_id="D9", run_ids=["R1", "R2"])
        with patch("tools.run_pipeline.fail_directive_best_effort"), patch(
            "tools.run_pipeline.fail_run_best_effort",
            side_effect=[True, False],
        ), redirect_stdout(out):
            code = map_pipeline_error(err)

        self.assertEqual(code, 1)
        self.assertEqual(
            out.getvalue().strip().splitlines(),
            [
                "[ORCHESTRATOR] Execution Failed: fatal",
                "[ORCHESTRATOR] Performing fail-safe state cleanup...",
                "[CLEANUP] Marking run R1 as FAILED",
            ],
        )


if __name__ == "__main__":
    unittest.main()
