"""
reporting_stage.py — Stage-2: Compilation
Purpose: Wraps run_stage2_compilation() from stage_symbol_execution.
Authority: Orchestrator Refactor Phase 6
"""

from __future__ import annotations
from tools.pipeline_utils import PipelineContext


class ReportingStage:
    """
    Stage-2: Engine resolution + compilation scan.

    Calls run_stage2_compilation() from stage_symbol_execution.
    Does not implement any logic directly.
    """
    stage_id = "REPORTING"
    stage_name = "Stage-2 Compilation"

    def run(self, context: PipelineContext) -> None:
        from tools.orchestration.stage_symbol_execution import run_stage2_compilation
        print(f"[{self.stage_id}] Starting Stage-2 Compilation for: {context.directive_id}")
        run_stage2_compilation(context)
        print(f"[{self.stage_id}] Stage-2 Compilation complete.")
