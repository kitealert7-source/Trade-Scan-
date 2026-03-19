"""
preflight_stage.py — Semantic Validation Stage (Preflight)
"""

from __future__ import annotations

import shutil

from config.state_paths import RUNS_DIR
from tools.pipeline_utils import PipelineContext, PipelineStateManager
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

        # Atomic Run Provisioning: initialize run state dirs here, after all admission
        # gates have passed, so a Preflight failure cannot leave stranded empty run folders.
        newly_created_dirs = []
        if context.current_state not in ("SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"):
            print(f"[{self.stage_id}] Initializing symbol run states...")
            for run_id in context.run_ids:
                run_dir = RUNS_DIR / run_id
                is_new = not run_dir.exists()
                PipelineStateManager(run_id, directive_id=context.directive_id).initialize()
                if is_new:
                    newly_created_dirs.append(run_dir)

        try:
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
        except PipelineAdmissionPause:
            # Clean pause (provision-only or human review) — keep run dirs for resume.
            raise
        except Exception:
            # Hard failure — prune only the dirs created this run to avoid stranded folders.
            for run_dir in newly_created_dirs:
                if run_dir.exists():
                    shutil.rmtree(run_dir, ignore_errors=True)
                    print(f"[{self.stage_id}] Cleaned up stranded run dir: {run_dir.name}")
            raise

        if should_stop:
            print(f"[{self.stage_id}] Preflight requested halt.")
            raise PipelineAdmissionPause(
                "Pipeline paused cleanly for --provision-only or human implementation.",
                directive_id=context.directive_id,
                run_ids=context.run_ids
            )
