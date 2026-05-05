"""Step 6 invariant hardening tests for pipeline orchestration.

REWRITTEN 2026-05-05 — Batch 3 test architecture modernization.

NOTE: FAILED directives no longer require manual reset.
BootstrapController now auto-creates a new attempt by design.
Old invariant intentionally retired (see
test_failed_state_creates_new_attempt below).

Old test pattern: patch tools.run_pipeline.{plan_runs_for_directive,
run_preflight_semantic_checks, run_symbol_execution_stages,
run_portfolio_and_post_stages} and call run_single_directive end-to-end.
Architecturally invalidated by commit 04c05c9 — those callables were
moved into Stage classes (PreflightStage, SymbolExecutionStage,
PortfolioStage) which import their own collaborators. Patches at the
run_pipeline import site succeeded but were no-ops because Stage
classes never dereference through tools.run_pipeline.

New pattern: test BootstrapController.prepare_context (state-machine
invariants) and individual Stage classes (resume-skip logic) at their
canonical mock boundaries. Each test asserts ONE responsibility owned
by ONE module.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.orchestration.pipeline_errors import PipelineExecutionError
from tools.orchestration.stage_preflight import run_preflight_semantic_checks
from tools.orchestration.stage_symbol_execution import run_symbol_execution_stages
from tools.run_pipeline import map_pipeline_error


def _directive_yaml(directive_id: str, symbols: list[str]) -> str:
    symbol_lines = "\n".join(f"  - {s}" for s in symbols)
    return f"""test:
  name: {directive_id}
symbols:
{symbol_lines}
"""


# ---------------------------------------------------------------------------
# Shared bootstrap-mocks helper
# ---------------------------------------------------------------------------


def _patch_bootstrap_dependencies(
    *,
    state_seq: list[str],
    directive_id: str,
):
    """Patch BootstrapController's collaborators at their canonical
    sites (`tools.orchestration.bootstrap_controller.<name>`). Returns
    `(stack, state_mgr_mock, transition_mock, admission_mock,
    planning_mock)` — caller uses `with stack:`.

    Why these patch sites: Stage classes import their collaborators
    from `tools.orchestration.<module>`. Patching `tools.run_pipeline.<X>`
    succeeds but is a no-op because the Stage class never dereferences
    through run_pipeline. The bootstrap_controller module is the
    canonical site for what BootstrapController actually uses.
    """
    state_iter = iter(state_seq + [state_seq[-1]] * 50)  # tail-padded

    state_mgr = MagicMock()
    state_mgr.initialize = MagicMock(return_value=None)
    state_mgr.get_state = MagicMock(side_effect=lambda: next(state_iter))
    state_mgr.create_new_attempt = MagicMock(return_value=None)

    stack = ExitStack()

    def _find_directive_path(active_dir, did):
        candidate = active_dir / f"{did}.txt"
        return candidate if candidate.exists() else None

    stack.enter_context(patch(
        "tools.orchestration.bootstrap_controller.find_directive_path",
        side_effect=_find_directive_path,
    ))
    stack.enter_context(patch(
        "tools.orchestration.bootstrap_controller.parse_directive",
        return_value={"Symbols": ["EURUSD"], "Strategy": directive_id},
    ))
    stack.enter_context(patch(
        "tools.orchestration.bootstrap_controller.DirectiveStateManager",
        return_value=state_mgr,
    ))
    admission = stack.enter_context(patch(
        "tools.orchestration.bootstrap_controller.AdmissionStage.run",
        return_value=None,
    ))
    # Planning stage seeds run_ids on ctx so downstream stages have
    # something to iterate; mirrors what real planning would do.
    planning = stack.enter_context(patch(
        "tools.orchestration.bootstrap_controller.DirectivePlanningStage.run",
        side_effect=lambda ctx: setattr(ctx, "run_ids", ["RID1"]) or
                                setattr(ctx, "symbols", ["EURUSD"]),
    ))
    transition = stack.enter_context(patch(
        "tools.orchestration.bootstrap_controller.transition_directive_state",
        return_value=None,
    ))
    return stack, state_mgr, transition, admission, planning


def _seed_directive_in_inbox(root: Path, directive_id: str) -> None:
    """BootstrapController checks `root/backtest_directives/INBOX/<did>.txt`
    via find_directive_path. The mock above honours filesystem presence
    so the file must exist for the resolution to succeed."""
    inbox = root / "backtest_directives" / "INBOX"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{directive_id}.txt").write_text(
        _directive_yaml(directive_id, ["EURUSD"]),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# BootstrapController — state-machine invariants
# ---------------------------------------------------------------------------


class TestBootstrapControllerStateMachine(unittest.TestCase):
    """All directive-state recovery semantics live in
    BootstrapController.prepare_context (see bootstrap_controller.py
    lines 67-89). StageRunner sees only the resulting ctx and iterates
    STAGE_REGISTRY; per-stage skip logic is internal.
    """

    def test_resume_state_propagates_to_context(self):
        """SYMBOL_RUNS_COMPLETE → ctx.current_state reflects it.
        StageRunner downstream uses ctx.current_state for per-stage
        skip; BootstrapController just propagates without mutation."""
        from tools.orchestration.bootstrap_controller import BootstrapController

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_directive_in_inbox(root, "RESUME_CASE")

            stack, state_mgr, transition, _, _ = _patch_bootstrap_dependencies(
                state_seq=["SYMBOL_RUNS_COMPLETE"],
                directive_id="RESUME_CASE",
            )
            with stack:
                ctx = BootstrapController(root).prepare_context(
                    directive_id="RESUME_CASE",
                    provision_only=False,
                )

        self.assertEqual(ctx.current_state, "SYMBOL_RUNS_COMPLETE")
        self.assertEqual(ctx.directive_id, "RESUME_CASE")
        self.assertEqual(ctx.run_ids, ["RID1"])  # seeded by planning mock
        # SYMBOL_RUNS_COMPLETE is not a state-machine trigger; neither
        # transition nor new-attempt should have fired.
        transition.assert_not_called()
        state_mgr.create_new_attempt.assert_not_called()

    def test_failed_provision_only_calls_transition(self):
        """FAILED + provision_only=True → transition_directive_state is
        invoked once with INITIALIZED. The old test also asserted
        preflight ran and symbol/portfolio didn't, but those are
        StageRunner concerns — BootstrapController only owns the
        FAILED→INITIALIZED transition."""
        from tools.orchestration.bootstrap_controller import BootstrapController

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_directive_in_inbox(root, "PROVISION_RESET_CASE")

            stack, state_mgr, transition, _, _ = _patch_bootstrap_dependencies(
                state_seq=["FAILED", "INITIALIZED"],
                directive_id="PROVISION_RESET_CASE",
            )
            with stack:
                ctx = BootstrapController(root).prepare_context(
                    directive_id="PROVISION_RESET_CASE",
                    provision_only=True,
                )

        transition.assert_called_once_with("PROVISION_RESET_CASE", "INITIALIZED")
        # create_new_attempt is the FAILED + non-provision path; should
        # NOT fire here.
        state_mgr.create_new_attempt.assert_not_called()
        # ctx.current_state reflects the post-reset value (INITIALIZED).
        self.assertEqual(ctx.current_state, "INITIALIZED")

    def test_failed_state_creates_new_attempt(self):
        """FAILED + provision_only=False → dir_state_mgr.create_new_attempt()
        is invoked. NO exception.

        SEMANTIC INVERSION from the pre-04c05c9 invariant. Old test
        (test_failed_directive_without_provision_requires_manual_reset)
        asserted PipelineExecutionError("must be reset"). New invariant
        per bootstrap_controller.py line 86-89: the controller
        auto-creates a new attempt and continues. Manual reset is no
        longer required."""
        from tools.orchestration.bootstrap_controller import BootstrapController

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_directive_in_inbox(root, "FAILED_AUTO_ATTEMPT")

            stack, state_mgr, transition, _, _ = _patch_bootstrap_dependencies(
                state_seq=["FAILED", "INITIALIZED"],  # post-attempt state
                directive_id="FAILED_AUTO_ATTEMPT",
            )
            with stack:
                # Critical: must NOT raise. Old test asserted raises here.
                ctx = BootstrapController(root).prepare_context(
                    directive_id="FAILED_AUTO_ATTEMPT",
                    provision_only=False,
                )

        state_mgr.create_new_attempt.assert_called_once()
        # transition is the provision_only path, must not fire here.
        transition.assert_not_called()
        # ctx.current_state reflects the post-attempt fetched state.
        self.assertEqual(ctx.current_state, "INITIALIZED")

    def test_portfolio_complete_raises_clean_exit(self):
        """PORTFOLIO_COMPLETE → PipelineExecutionError with exit_code=0.
        run_pipeline.run_single_directive catches this and returns
        cleanly without flagging the directive as failed."""
        from tools.orchestration.bootstrap_controller import BootstrapController

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_directive_in_inbox(root, "ALREADY_DONE")

            stack, state_mgr, transition, _, _ = _patch_bootstrap_dependencies(
                state_seq=["PORTFOLIO_COMPLETE"],
                directive_id="ALREADY_DONE",
            )
            with stack:
                with self.assertRaises(PipelineExecutionError) as cm:
                    BootstrapController(root).prepare_context(
                        directive_id="ALREADY_DONE",
                        provision_only=False,
                    )

        self.assertIn("already COMPLETE", str(cm.exception))
        self.assertEqual(cm.exception.exit_code, 0)
        # No state mutation on already-complete.
        transition.assert_not_called()
        state_mgr.create_new_attempt.assert_not_called()


# ---------------------------------------------------------------------------
# PreflightStage — resume-skip via current_state
# ---------------------------------------------------------------------------


class TestPreflightStageResumeSkip(unittest.TestCase):
    """When ctx.current_state is in {SYMBOL_RUNS_COMPLETE,
    PORTFOLIO_COMPLETE}, PreflightStage skips run-dir initialization
    (preflight_stage.py line 31). This is the per-stage skip half of
    the resume-completeness invariant; the other half (BootstrapController
    propagating current_state to ctx) is covered above.
    """

    def _build_ctx(self, current_state: str):
        from tools.pipeline_utils import PipelineContext

        ctx = PipelineContext(
            directive_id="TEST",
            directive_path=Path("/tmp/test.txt"),
            project_root=Path("/tmp"),
            python_exe="python",
            provision_only=False,
        )
        ctx.directive_config = {"Strategy": "TEST"}
        ctx.run_ids = ["RID_1", "RID_2"]
        ctx.symbols = ["EURUSD", "USDJPY"]
        ctx.directive_state_manager = MagicMock()
        ctx.current_state = current_state
        return ctx

    def test_skips_run_dir_init_on_symbol_runs_complete(self):
        """current_state=SYMBOL_RUNS_COMPLETE → PipelineStateManager(...)
        .initialize() is NOT called for any run."""
        from tools.orchestration.preflight_stage import PreflightStage

        psm_mock = MagicMock()
        with patch(
            "tools.orchestration.preflight_stage.PipelineStateManager",
            return_value=psm_mock,
        ), patch(
            "tools.orchestration.preflight_stage.run_preflight_semantic_checks",
            return_value=False,
        ):
            ctx = self._build_ctx("SYMBOL_RUNS_COMPLETE")
            PreflightStage().run(ctx)

        psm_mock.initialize.assert_not_called()

    def test_initializes_run_dirs_on_initialized(self):
        """current_state=INITIALIZED → PipelineStateManager(...).initialize()
        called once per run_id (control case for the skip-test above)."""
        from tools.orchestration.preflight_stage import PreflightStage

        psm_mock = MagicMock()
        with patch(
            "tools.orchestration.preflight_stage.PipelineStateManager",
            return_value=psm_mock,
        ), patch(
            "tools.orchestration.preflight_stage.run_preflight_semantic_checks",
            return_value=False,
        ):
            ctx = self._build_ctx("INITIALIZED")
            PreflightStage().run(ctx)

        # Two run_ids → two initialize calls.
        self.assertEqual(psm_mock.initialize.call_count, 2)


# ---------------------------------------------------------------------------
# Stage-1 partial failure — multi-symbol invariant
# ---------------------------------------------------------------------------


class TestMultiSymbolPartialFailureInvariant(unittest.TestCase):
    """When per-symbol Stage-1 execution fails on one run_id, only that
    run is marked FAILED — sibling runs that already passed Stage-1
    keep their STAGE_1_COMPLETE status.

    The pre-rewrite skip note claimed the artifact moved to
    runs/<rid>/data/. That was wrong. The canonical Stage-1 artifact
    check is still at `BACKTESTS_DIR / <clean_id>_<symbol> / raw /
    results_tradelevel.csv` (stage_symbol_execution.py:156). The real
    coupling problems were:
      1. BACKTESTS_DIR is anchored on the real TradeScan_State sibling
         (via path_authority), not on the test's project_root. We
         can't seed there without polluting state.
      2. The run_stage1_execution loop uses claim_next_planned_run +
         list_runs + ensure_registry + update_run_state — all of
         which need either real registry I/O or stubs.

    Test now monkey-patches BACKTESTS_DIR / RUNS_DIR / the registry
    helpers in the stage_symbol_execution module to a tmp dir, then
    calls run_stage1_execution(ctx) directly (bypassing the Stage-2
    artifact-recheck wrapper that was the real source of the failures
    in the wrapper-based test).
    """

    def test_stage1_partial_failure_marks_only_failing_run(self):
        from tools.pipeline_utils import PipelineContext

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_backtests = root / "backtests"
            fake_runs = root / "runs"
            fake_runs.mkdir(parents=True, exist_ok=True)

            # Seed RID1's success artifact at the canonical location
            # the inline check (stage_symbol_execution.py:156) reads.
            (fake_backtests / "CASE_EURUSD" / "raw").mkdir(parents=True, exist_ok=True)
            (fake_backtests / "CASE_EURUSD" / "raw" / "results_tradelevel.csv").write_text(
                "x\n1\n", encoding="utf-8"
            )

            # claim_next_planned_run returns claims sequentially then None.
            claims = iter([
                {"run_id": "RID1", "symbol": "EURUSD", "strategy": "CASE"},
                {"run_id": "RID2", "symbol": "USDJPY", "strategy": "CASE"},
                None,
            ])

            class FakeManager:
                def __init__(self, run_id, **_kw):
                    self.run_id = run_id
                    self.run_dir = fake_runs / run_id
                    self.run_dir.mkdir(parents=True, exist_ok=True)

                def get_state_data(self):
                    return {"current_state": "IDLE"}

                def record_heartbeat(self):
                    pass

                def _append_audit_log(self, *_args, **_kwargs):
                    pass

            sse_mod_patches = [
                patch("tools.orchestration.stage_symbol_execution.BACKTESTS_DIR", fake_backtests),
                patch("tools.orchestration.stage_symbol_execution.RUNS_DIR", fake_runs),
                patch(
                    "tools.orchestration.stage_symbol_execution.PipelineStateManager",
                    side_effect=lambda rid, **kw: FakeManager(rid, **kw),
                ),
                patch(
                    "tools.orchestration.stage_symbol_execution.claim_next_planned_run",
                    side_effect=lambda *_a, **_kw: next(claims),
                ),
                patch("tools.orchestration.stage_symbol_execution.ensure_registry"),
                patch(
                    "tools.orchestration.stage_symbol_execution.requeue_running_runs",
                    return_value=0,
                ),
                patch(
                    "tools.orchestration.stage_symbol_execution.list_runs",
                    return_value=[
                        {"run_id": "RID1", "symbol": "EURUSD", "strategy": "CASE"},
                        {"run_id": "RID2", "symbol": "USDJPY", "strategy": "CASE"},
                    ],
                ),
                patch("tools.orchestration.stage_symbol_execution.update_run_state"),
                patch("tools.orchestration.stage_symbol_execution.log_run_to_registry"),
                patch("tools.skill_loader.run_skill",
                      side_effect=[None, RuntimeError("stage1 boom")]),
            ]
            with ExitStack() as stack:
                for p in sse_mod_patches:
                    stack.enter_context(p)
                trs_mock = stack.enter_context(patch(
                    "tools.orchestration.stage_symbol_execution.transition_run_state"
                ))

                ctx = PipelineContext(
                    directive_id="CASE",
                    directive_path=root / "directive.txt",
                    project_root=root,
                    python_exe="python",
                    provision_only=False,
                )
                ctx.directive_config = {"Strategy": "CASE",
                                         "Symbols": ["EURUSD", "USDJPY"]}
                ctx.run_ids = ["RID1", "RID2"]
                ctx.symbols = ["EURUSD", "USDJPY"]
                ctx.registry_path = root / "registry.json"

                from tools.orchestration.stage_symbol_execution import run_stage1_execution
                with self.assertRaises(RuntimeError) as cm:
                    run_stage1_execution(ctx)

        self.assertIn("stage1 boom", str(cm.exception))
        trs_mock.assert_has_calls(
            [
                call("RID1", "STAGE_1_COMPLETE"),
                call("RID2", "FAILED"),
            ],
            any_order=False,
        )


# ---------------------------------------------------------------------------
# Golden output stability — preserved unchanged from pre-rewrite
# ---------------------------------------------------------------------------


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
