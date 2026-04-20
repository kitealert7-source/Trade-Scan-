"""
aggregation_stage.py — Stage-3: Aggregation + Cardinality Gate
Purpose: Wraps run_stage3_aggregation() from stage_symbol_execution.
Authority: Orchestrator Refactor Phase 6

Guardrail: The cardinality gate LIVES INSIDE run_stage3_aggregation().
If the gate fails, a PipelineExecutionError is raised here, and ManifestBindingStage
is NEVER reached (StageRunner fail-fast behaviour).
"""

from __future__ import annotations
from tools.pipeline_utils import PipelineContext


class AggregationStage:
    """
    Stage-3: Portfolio aggregation compiler + cardinality enforcement gate.

    Calls run_stage3_aggregation() from stage_symbol_execution.
    Cardinality validation is inside the underlying function.
    Failure here STOPS the runner — ManifestBindingStage is never reached.
    """
    stage_id = "AGGREGATION"
    stage_name = "Stage-3 Aggregation"

    def run(self, context: PipelineContext) -> None:
        from tools.orchestration.stage_symbol_execution import run_stage3_aggregation
        print(f"[{self.stage_id}] Starting Stage-3 Aggregation for: {context.directive_id}")
        run_stage3_aggregation(context)
        print(f"[{self.stage_id}] Stage-3 Aggregation and cardinality gate passed.")
