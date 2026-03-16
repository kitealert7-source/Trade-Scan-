"""
preflight_stage.py — Semantic Validation Stage (Preflight)
"""

from __future__ import annotations

from tools.pipeline_utils import PipelineContext
from tools.orchestration.pipeline_stages import run_preflight_semantic_checks
from tools.orchestration.execution_adapter import run_command
from tools.orchestration.pipeline_errors import PipelineAdmissionPause

class PreflightStage:
    """
    Stage 0: Semantic Preflight validation.
    Handles semantic gate verification and stops execution if requested.
    """
    stage_id = "PREFLIGHT"
    stage_name = "Semantic Validation"

    def run(self, context: PipelineContext) -> None:
        print(f"[{self.stage_id}] Starting Semantic Validation for: {context.directive_id}")
        
        dir_state_mgr = context.directive_state_manager
        
        should_stop = run_preflight_semantic_checks(
            clean_id=context.directive_id,
            d_path=context.directive_path,
            p_conf=context.directive_config,
            run_ids=context.run_ids,
            symbols=context.symbols,
            dir_state_mgr=dir_state_mgr,
            provision_only=context.provision_only,
            project_root=context.project_root,
            python_exe=context.python_exe,
            run_command=run_command
        )
        
        if should_stop:
            print(f"[{self.stage_id}] Preflight requested halt.")
            raise PipelineAdmissionPause(
                "Pipeline paused cleanly for --provision-only or human implementation.",
                directive_id=context.directive_id,
                run_ids=context.run_ids
            )
