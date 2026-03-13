# Run Registry Execution Model - Implementation Report
**Date:** 2026-03-12

## Scope
Implemented a run-registry based execution model so symbol work is planned to disk and claimed by workers from registry state (`PLANNED -> RUNNING -> COMPLETE/FAILED`).

## Key Changes
- Added run registry persistence and claim/update logic:
  - `tools/orchestration/run_registry.py`
- Added directive run planner:
  - `tools/orchestration/run_planner.py`
- Updated orchestrator planning flow:
  - `tools/run_pipeline.py`
  - plans runs first and persists `runs/<DIRECTIVE_ID>/run_registry.json`
  - passes registry path into symbol execution stage
- Updated symbol execution stage to worker-claim model:
  - `tools/orchestration/stage_symbol_execution.py`
  - claims planned runs from registry, marks `RUNNING`, executes, marks `COMPLETE`/`FAILED`
  - re-queues interrupted `RUNNING` entries to `PLANNED` on resume
- Updated dispatcher signature:
  - `tools/orchestration/pipeline_stages.py`

## Tests Added/Updated
- Added: `tests/test_run_registry_planner.py`
- Updated: `tests/test_step6_state_machine_invariants.py` (planner patch points)

## Validation
Executed:
- `python -m py_compile ...` (updated orchestration + tests)
- `pytest -q tests/test_run_registry_planner.py tests/test_step6_state_machine_invariants.py tests/test_pipeline_error_model.py tests/test_pre_execution_workflow.py tests/test_transition_service.py tests/test_provision_only_integration.py tests/test_resume_fsm.py tests/test_resume_artifacts.py tests/test_sweep_registry_hash_compat.py tests/test_strategy_provisioner_compat.py`

Result:
- `31 passed`
