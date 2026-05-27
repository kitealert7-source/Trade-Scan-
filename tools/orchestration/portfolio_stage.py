"""
portfolio_stage.py — Stage-4: Portfolio Evaluation & Post-Processing
Purpose: Wraps run_portfolio_and_post_stages() from stage_portfolio.
Authority: Orchestrator Refactor Phase 7

This stage runs AFTER ManifestBindingStage (SYMBOL_RUNS_COMPLETE).
StageRunner fail-fast guarantees this stage only runs when all symbol runs succeeded.

Phase 2b (2026-05-27): Stage-4 entry now acquires a FileLock co-located
with Master_Portfolio_Sheet.xlsx. Only one directive at a time may enter
Stage 4 — deterministic exclusivity over the shared portfolio ledger
write surface. Replaces the conceptual role of the 15s inter-directive
cooldown with explicit, observable serialization (15-min hard timeout,
60s stale-wait warning).
"""

from __future__ import annotations
from tools.pipeline_utils import PipelineContext


class PortfolioStage:
    """
    Stage-4: Portfolio evaluation, capital wrapper, profile selector, and
    deployable artifact verification.

    Calls run_portfolio_and_post_stages() from stage_portfolio under a
    FileLock that gates ALL writes to Master_Portfolio_Sheet.xlsx and
    Filtered_Strategies_Passed.xlsx.

    Emits directive FSM transition to PORTFOLIO_COMPLETE (inside the underlying function).

    Rule: This stage does NOT own FSM transitions directly.
    Rule: This stage only runs after ManifestBindingStage succeeds (StageRunner guarantee).
    Rule: Only one directive at a time may enter the locked region.
    """
    stage_id = "PORTFOLIO"
    stage_name = "Stage-4 Portfolio Evaluation"

    def run(self, context: PipelineContext) -> None:
        from tools.orchestration.stage_portfolio import run_portfolio_and_post_stages
        from tools.orchestration.execution_adapter import run_command
        from tools.pipeline_locks import acquire_with_stale_warn
        from config.state_paths import STRATEGIES_DIR

        # Lock file co-located with the protected resource. Same path-style
        # convention as Stage 3 (Strategy_Master_Filter.xlsx.lock). The OS
        # auto-releases the lock if the holder process dies, so a worker
        # crash mid-Stage-4 does NOT leave the lock stuck.
        _lock_path = (STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx").with_suffix(".lock")

        print(f"[{self.stage_id}] Starting Portfolio Evaluation for: {context.directive_id}")
        with acquire_with_stale_warn(
            _lock_path,
            lock_name="stage4_portfolio_sheet",
            directive_id=context.directive_id,
            stage_id=self.stage_id,
            # Defaults: 15-min hard timeout, 60s stale-wait warning.
            # When telemetry plumbing reaches this stage (Phase 3+),
            # pass the parent's TelemetryWriter for structured events.
        ):
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
