"""
bootstrap_controller.py — Bootstraps environment and context for pipeline execution.
Purpose: Encapsulates admission gates, planning, and context initialization.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.pipeline_utils import PipelineContext, parse_directive, DirectiveStateManager
from tools.orchestration.admission_controller import AdmissionStage
from tools.orchestration.planning_stages import DirectivePlanningStage
from tools.orchestration.pre_execution import find_directive_path
from tools.orchestration.transition_service import transition_directive_state
from tools.orchestration.pipeline_errors import PipelineExecutionError


class BootstrapController:
    """Handles initialization, admission, and planning before the StageRunner."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def prepare_context(self, directive_id: str, provision_only: bool) -> PipelineContext:
        active_dir = self.project_root / "backtest_directives" / "INBOX"
        active_backup_dir = self.project_root / "backtest_directives" / "active_backup"
        python_exe = sys.executable

        d_path = find_directive_path(active_backup_dir, directive_id)
        if not d_path:
            d_path = find_directive_path(active_dir, directive_id)
            
        if not d_path:
            raise PipelineExecutionError(
                f"Directive file not found for ID: {directive_id}. Admitted directives must reside in: {active_backup_dir} or {active_dir}",
                directive_id=directive_id,
                fail_directive=False,
                fail_runs=False,
            )

        ctx = PipelineContext(
            directive_id=directive_id,
            directive_path=d_path,
            project_root=self.project_root,
            python_exe=python_exe,
            provision_only=provision_only
        )

        # 1. Admission Gates
        AdmissionStage().run(ctx)

        # 2. Parse Directive
        p_conf = parse_directive(d_path)
        ctx.directive_config = p_conf

        # 3. State Management
        dir_state_mgr = DirectiveStateManager(directive_id)
        dir_state_mgr.initialize()
        ctx.directive_state_manager = dir_state_mgr

        current_dir_state = dir_state_mgr.get_state()
        ctx.current_state = current_dir_state
        print(f"[ORCHESTRATOR] Directive State: {current_dir_state}")

        # Resume Safety logic
        if current_dir_state == "PORTFOLIO_COMPLETE":
             print(f"[ORCHESTRATOR] Directive {directive_id} is already COMPLETE. Aborting.")
             # Raise to exit gracefully from orchestrator without failing
             raise PipelineExecutionError(
                 f"Directive {directive_id} is already COMPLETE. Aborting.",
                 directive_id=directive_id,
                 fail_directive=False,
                 fail_runs=False,
                 exit_code=0
             )
             
        elif current_dir_state == "FAILED":
             if provision_only:
                 print(f"[ORCHESTRATOR] Directive {directive_id} is FAILED. Resetting for --provision-only run.")
                 transition_directive_state(directive_id, "INITIALIZED")
                 current_dir_state = dir_state_mgr.get_state()
                 ctx.current_state = current_dir_state
                 print(f"[ORCHESTRATOR] Directive State after reset: {current_dir_state}")
             else:
                 print(f"[ORCHESTRATOR] Directive {directive_id} is FAILED. Provisioning next attempt instead of halting.")
                 dir_state_mgr.create_new_attempt()
                 current_dir_state = dir_state_mgr.get_state()
                 ctx.current_state = current_dir_state

        # 4. Planning Stage
        DirectivePlanningStage().run(ctx)

        return ctx
