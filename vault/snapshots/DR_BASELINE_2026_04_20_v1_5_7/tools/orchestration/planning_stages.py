"""
planning_stages.py — Directive Planning Phase
Purpose: Encapsulates run ID generation and symbol mapping logic.
Authority: Orchestrator Refactor Proposal v3.5
"""

from __future__ import annotations
from pathlib import Path
from tools.pipeline_utils import PipelineContext
from tools.orchestration.pipeline_errors import PipelineExecutionError

class DirectivePlanningStage:
    """
    Planning Phase (Bootstrap):
    - Generates Run IDs based on directive config.
    - Performs symbol mapping.
    - Initializes the run registry for the current execution.
    """
    stage_id = "PLANNING"
    stage_name = "Directive Planning"

    def run(self, context: PipelineContext) -> None:
        """Execute the planning logic."""
        from tools.orchestration.run_planner import plan_runs_for_directive
        
        print(f"[{self.stage_id}] Starting run planning for: {context.directive_id}")
        
        try:
            p_conf = context.directive_config
            symbols = p_conf.get("Symbols", p_conf.get("symbols", context.symbols))
            if isinstance(symbols, str):
                symbols = [symbols]
            
            strategy_id = p_conf.get("Strategy", p_conf.get("strategy")) or context.directive_id
            
            planned_runs, registry_path = plan_runs_for_directive(
                directive_id=context.directive_id,
                directive_path=context.directive_path,
                strategy_id=strategy_id,
                symbols=symbols,
                project_root=context.project_root,
            )
            
            # Update context with results
            context.planned_runs = planned_runs
            context.run_ids = [run["run_id"] for run in planned_runs]
            context.symbols = [run["symbol"] for run in planned_runs]
            context.registry_path = registry_path
            
            print(f"[{self.stage_id}] Planning complete: {len(context.run_ids)} runs mapped across {len(context.symbols)} symbols.")
            
        except Exception as e:
            raise PipelineExecutionError(f"STAGE PLANNING FAILED: {e}", directive_id=context.directive_id) from e
