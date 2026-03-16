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
    """
    stage_id = "MANIFEST_BINDING"
    stage_name = "Artifact Binding & Run Close"

    def run(self, context: PipelineContext) -> None:
        from tools.orchestration.stage_symbol_execution import run_manifest_binding
        print(f"[{self.stage_id}] Starting Manifest Binding for: {context.directive_id}")
        run_manifest_binding(context)
        print(f"[{self.stage_id}] All runs bound. Directive state: SYMBOL_RUNS_COMPLETE.")
