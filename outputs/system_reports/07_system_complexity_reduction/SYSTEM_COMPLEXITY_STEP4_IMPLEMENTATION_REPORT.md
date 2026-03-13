# System Complexity Step-4 Implementation Report
**Date:** 2026-03-12  
**Step:** Separate migration/provision pipeline from execution pipeline

## Objective
Move directive migration and identity resolution into a dedicated pre-execution workflow so execution begins only after identity is finalized.

## Implemented Changes
### 1. Added dedicated pre-execution module
- `tools/orchestration/pre_execution.py`
- Introduced workflow functions:
  - `prepare_single_directive_for_execution(...)`
  - `prepare_batch_directives_for_execution(...)`
  - `run_auto_namespace_migration(...)`
  - `find_directive_path(...)`
  - signature-based identity resolution helpers

### 2. Rewired `run_pipeline.py` entry flow
- Single directive path now calls:
  - `prepare_single_directive_for_execution(...)` before `run_single_directive(...)`
- Batch path now calls:
  - `prepare_batch_directives_for_execution(...)` before processing directives
- `run_single_directive(...)` now accepts explicit `provision_only` argument instead of reading `sys.argv` internally.

### 3. Coordinator cleanup
- Removed in-file migration/identity helper functions from `run_pipeline.py`.
- Execution coordinator now starts with finalized directive identity.

## Added Tests
- `tests/test_pre_execution_workflow.py`
  - directive lookup
  - signature resolution preferring namespaced identity
  - single pre-exec identity finalization flow
  - batch pre-exec directive list flow

## Validation Evidence
Executed:
1. `python -m py_compile tools/run_pipeline.py tools/orchestration/pre_execution.py tools/orchestration/pipeline_stages.py tools/orchestration/transition_service.py`
2. `pytest -q tests/test_pre_execution_workflow.py tests/test_transition_service.py tests/test_provision_only_integration.py tests/test_sweep_registry_hash_compat.py tests/test_strategy_provisioner_compat.py`

Result:
- `13 passed`

## Complexity Impact
- `tools/run_pipeline.py` reduced to 418 lines.
- Pre-exec concerns isolated into `tools/orchestration/pre_execution.py` (111 lines).

## Outcome
Step 4 objective achieved:
- migration/provision preparation is now a dedicated pre-execution workflow,
- execution starts only after directive identity finalization,
- focused regression suite is passing.
