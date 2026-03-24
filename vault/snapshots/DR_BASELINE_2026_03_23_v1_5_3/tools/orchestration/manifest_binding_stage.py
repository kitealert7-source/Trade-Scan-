"""
manifest_binding_stage.py — Stage-3a: Artifact Binding & Run Close
Purpose: Wraps run_manifest_binding() from stage_symbol_execution.
Authority: Orchestrator Refactor Phase 6

Only runs after Stage-3 (AggregationStage) succeeds.
StageRunner fail-fast guarantees this.
"""

from __future__ import annotations
from tools.pipeline_utils import PipelineContext


class ManifestBindingStage:
    """
    Stage-3a: Per-run snapshot verification, artifact hashing, manifest write, and FSM close.

    Calls run_manifest_binding() from stage_symbol_execution.
    This stage only executes if AggregationStage succeeded (StageRunner fail-fast guarantee).
    Emits the directive FSM transition to SYMBOL_RUNS_COMPLETE.

    Skip guard: if the directive is already SYMBOL_RUNS_COMPLETE (e.g. Portfolio failed
    on a previous attempt, or --to-stage4 reset was used), binding is already done.
    Re-entering would cause an illegal FSM transition. Skip cleanly so PortfolioStage
    can be retried directly.

    Assumption: SYMBOL_RUNS_COMPLETE implies artifacts are valid.
    This is safe because run_manifest_binding() emits the FSM transition as its very
    last line (after all per-run artifact writes complete). A mid-flight crash leaves
    the state at the pre-binding value, not SYMBOL_RUNS_COMPLETE. The only unsafe path
    is manual directive_state.json surgery — not a normal pipeline operation.
    """
    stage_id = "MANIFEST_BINDING"
    stage_name = "Artifact Binding & Run Close"

    def run(self, context: PipelineContext) -> None:
        dir_state = context.directive_state_manager.get_state()
        if dir_state == "SYMBOL_RUNS_COMPLETE":
            print(
                f"[{self.stage_id}] Directive already SYMBOL_RUNS_COMPLETE — "
                "binding already done. Skipping to Portfolio."
            )
            return

        from tools.orchestration.stage_symbol_execution import run_manifest_binding
        print(f"[{self.stage_id}] Starting Manifest Binding for: {context.directive_id}")
        run_manifest_binding(context)
        print(f"[{self.stage_id}] All runs bound. Directive state: SYMBOL_RUNS_COMPLETE.")
