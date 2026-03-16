"""
symbol_execution_controller.py — Stage-1: Backtest Execution Controller
Purpose: Orchestrates the Stage-1 symbol execution loop only.
Authority: Orchestrator Refactor Proposal v3.5 / Phase 6

Phase 6: SymbolExecutionStage now covers Stage-1 ONLY.
  Stage-2 (Compilation)     -> ReportingStage
  Stage-3 (Aggregation)     -> AggregationStage
  Stage-3a (Manifest Bind)  -> ManifestBindingStage
"""

from __future__ import annotations
from tools.pipeline_utils import PipelineContext


class SymbolExecutionStage:
    """
    Stage-1: Backtest Execution Loop (Registry Worker).

    Orchestrates strategy snapshots + per-symbol backtest execution.
    Does NOT invoke Stage-2, Stage-3, or manifest binding.
    Those belong to the dedicated downstream stages in STAGE_REGISTRY.

    Rule: This stage does NOT loop symbols. Looping is handled by run_stage1_execution().
    Rule: This stage does NOT touch Directive FSM.
    """
    stage_id = "SYMBOL_EXECUTION"
    stage_name = "Symbol Execution (Stage 1)"

    def run(self, context: PipelineContext) -> None:
        from tools.orchestration.stage_symbol_execution import run_stage1_execution
        print(f"[{self.stage_id}] Starting Stage-1 Backtest Execution for: {context.directive_id}")
        run_stage1_execution(context)
        print(f"[{self.stage_id}] Stage-1 execution complete.")
