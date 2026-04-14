"""
portfolio_stage.py — Stage-4: Portfolio Evaluation & Post-Processing
Purpose: Wraps run_portfolio_and_post_stages() from stage_portfolio.
Authority: Orchestrator Refactor Phase 7

This stage runs AFTER ManifestBindingStage (SYMBOL_RUNS_COMPLETE).
StageRunner fail-fast guarantees this stage only runs when all symbol runs succeeded.
"""

from __future__ import annotations
from tools.pipeline_utils import PipelineContext


class PortfolioStage:
    """
    Stage-4: Portfolio evaluation, capital wrapper, profile selector, and
    deployable artifact verification.

    Calls run_portfolio_and_post_stages() from stage_portfolio.
    Emits directive FSM transition to PORTFOLIO_COMPLETE (inside the underlying function).

    Rule: This stage does NOT own FSM transitions directly.
    Rule: This stage only runs after ManifestBindingStage succeeds (StageRunner guarantee).
    """
    stage_id = "PORTFOLIO"
    stage_name = "Stage-4 Portfolio Evaluation"

    def run(self, context: PipelineContext) -> None:
        from tools.orchestration.stage_portfolio import run_portfolio_and_post_stages
        from tools.orchestration.execution_adapter import run_command

        print(f"[{self.stage_id}] Starting Portfolio Evaluation for: {context.directive_id}")
        run_portfolio_and_post_stages(
            clean_id=context.directive_id,
            p_conf=context.directive_config,
            run_ids=context.run_ids,
            symbols=context.symbols,
            project_root=context.project_root,
            python_exe=context.python_exe,
            run_command=run_command,
        )
        print(f"[{self.stage_id}] Portfolio evaluation complete.")
