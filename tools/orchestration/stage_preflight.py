"""Preflight and semantic admission stages."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.orchestration.pipeline_errors import (
    PipelineAdmissionPause,
    PipelineExecutionError,
)
from tools.orchestration.transition_service import (
    transition_directive_state,
    transition_run_states_if,
)


def run_preflight_semantic_checks(
    *,
    clean_id: str,
    d_path: Path,
    p_conf: dict,
    run_ids: list[str],
    symbols: list[str],
    dir_state_mgr,
    provision_only: bool,
    project_root: Path,
    python_exe: str,
    run_command,
) -> bool:
    """
    Execute preflight + semantic gates.

    Returns True when pipeline should stop early (provision-only).
    """
    live_state = dir_state_mgr.get_state()
    preflight_skip = {
        "PREFLIGHT_COMPLETE",
        "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
        "SYMBOL_RUNS_COMPLETE",
        "PORTFOLIO_COMPLETE",
    }

    if live_state not in preflight_skip:
        print("[ORCHESTRATOR] Starting Preflight Checks...")
        try:
            run_command([python_exe, "tools/exec_preflight.py", clean_id], "Preflight")
        except subprocess.CalledProcessError as err:
            if err.returncode == 2:
                print("\n============================================================")
                print("[ADMISSION GATE] STRATEGY REQUIRES HUMAN IMPLEMENTATION")
                print("============================================================")
                print("ACTION: Please open the generated strategy file and implement `check_entry` and `check_exit`.")
                print("STATE: Pipeline paused cleanly. Rerun after implementation.")
                raise PipelineAdmissionPause(
                    "Preflight admission gate paused execution pending human implementation.",
                    directive_id=clean_id,
                    run_ids=run_ids,
                ) from err
            raise err

        transition_run_states_if(run_ids, "PREFLIGHT_COMPLETE", {"IDLE"})
        transition_directive_state(clean_id, "PREFLIGHT_COMPLETE")
    else:
        print(f"[ORCHESTRATOR] Preflight already complete (state={live_state}). Checking Semantic Status...")

    check_state = dir_state_mgr.get_state()
    if check_state == "PREFLIGHT_COMPLETE":
        print("[ORCHESTRATOR] Starting Stage-0.5: Semantic Validation...")
        from tools.semantic_validator import validate_semantic_signature

        try:
            validate_semantic_signature(str(d_path))
            transition_run_states_if(
                run_ids,
                "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                {"PREFLIGHT_COMPLETE"},
            )
            transition_directive_state(clean_id, "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
            print("[ORCHESTRATOR] Semantic Validation PASSED.")
        except Exception as err:
            if "PROVISION_REQUIRED" in str(err):
                print("\n============================================================")
                print("[ADMISSION GATE] STRATEGY REQUIRES HUMAN IMPLEMENTATION")
                print("============================================================")
                print(f"Details: {err}")
                print("ACTION: Please open the generated strategy.py file and implement `check_entry` and `check_exit`.")
                print("STATE: Pipeline paused cleanly. Rerun after implementation.")
                raise PipelineAdmissionPause(
                    f"Semantic admission gate paused execution: {err}",
                    directive_id=clean_id,
                    run_ids=run_ids,
                ) from err

            raise PipelineExecutionError(
                f"Semantic Validation FAILED: {err}",
                directive_id=clean_id,
                run_ids=run_ids,
            ) from err
    elif check_state == "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID":
        print("[ORCHESTRATOR] Semantic Validation already COMPLETE. Resuming...")

    cov_state = dir_state_mgr.get_state()
    if cov_state in ("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",):
        cov_strategy_id = p_conf.get("Strategy", p_conf.get("strategy")) or clean_id
        cov_strategy_path = project_root / "strategies" / cov_strategy_id / "strategy.py"
        if cov_strategy_path.exists():
            try:
                from governance.semantic_coverage_checker import check_semantic_coverage

                check_semantic_coverage(str(d_path), str(cov_strategy_path))
                print("[ORCHESTRATOR] Stage-0.55 Semantic Coverage Check PASSED.")
            except RuntimeError as err:
                if "SEMANTIC_COVERAGE_FAILURE" in str(err):
                    raise PipelineExecutionError(
                        str(err),
                        directive_id=clean_id,
                        run_ids=run_ids,
                    ) from err
                raise

    if provision_only:
        strategy_path = project_root / "strategies" / clean_id / "strategy.py"
        print(f"[PROVISION-ONLY] Strategy provisioned at: {strategy_path}")
        print("[PROVISION-ONLY] Human review required before execution.")
        print("[PROVISION-ONLY] Re-run without --provision-only after review.")
        return True

    live_state_075 = dir_state_mgr.get_state()
    if live_state_075 == "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID":
        from tools.strategy_dryrun_validator import validate_strategy_dryrun

        dryrun_ok = validate_strategy_dryrun(clean_id, symbols[0], d_path)
        if not dryrun_ok:
            raise PipelineExecutionError(
                "Stage-0.75 Dry-Run Validation FAILED.",
                directive_id=clean_id,
                run_ids=run_ids,
            )

    return False
