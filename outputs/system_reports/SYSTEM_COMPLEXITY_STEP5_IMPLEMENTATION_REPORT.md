# System Complexity Step-5 Implementation Report
**Date:** 2026-03-12  
**Step:** Simplify error handling model

## Objective
Replace scattered stage-level exits/cleanup branches with typed pipeline errors and one top-level failure mapper in the orchestrator.

## Implemented Changes
### 1. Added typed orchestration error model
- Added `tools/orchestration/pipeline_errors.py`
- Introduced:
  - `PipelineError` (base)
  - `PipelineAdmissionPause` (non-fatal pause; exit code 0)
  - `PipelineExecutionError` (fatal error with cleanup policy flags)

### 2. Centralized failure mapping in orchestrator
- Updated `tools/run_pipeline.py`
- Added `map_pipeline_error(err)` as single top-level mapper.
- Standardized handling:
  - admission pause -> clean pause (no fail-state mutation)
  - fatal error -> optional directive fail + optional run fail cleanup
- Main entry now maps `PipelineError` through this function.

### 3. Removed stage-level hard exits from orchestration stages
- Updated `tools/orchestration/pipeline_stages.py`
- Replaced `sys.exit(...)` paths with typed raises:
  - admission gate pauses now raise `PipelineAdmissionPause`
  - fatal validation/artifact failures now raise `PipelineExecutionError`
- Removed direct in-stage run/directive fail cleanup calls that duplicated orchestrator responsibilities.

### 4. Updated directive pipeline fatal paths to typed errors
- Updated `tools/run_pipeline.py` directive-gate paths to raise `PipelineExecutionError` instead of direct exits.
- Batch mode now fail-fast by re-raising typed errors to top-level mapper.

## Added Tests
- Added `tests/test_pipeline_error_model.py`
  - validates pause path (exit 0, no cleanup)
  - validates fatal path (directive + run cleanup)
  - validates cleanup policy flags (`fail_directive=False`, `fail_runs=False`)

## Validation Evidence
Executed:
1. `python -m py_compile tools/run_pipeline.py tools/orchestration/pipeline_errors.py tools/orchestration/pipeline_stages.py tools/orchestration/pre_execution.py tools/orchestration/transition_service.py`
2. `pytest -q tests/test_pipeline_error_model.py tests/test_pre_execution_workflow.py tests/test_transition_service.py tests/test_provision_only_integration.py tests/test_sweep_registry_hash_compat.py tests/test_strategy_provisioner_compat.py`

Result:
- `16 passed`

## Outcome
Step 5 objective achieved:
- typed orchestration error model is in place,
- stage modules no longer terminate process directly,
- failure/pause behavior is routed through one top-level mapper with explicit cleanup policy.

## Addendum (Pre-Step 6)
- Split stage implementation by pipeline phase:
  - `tools/orchestration/stage_preflight.py`
  - `tools/orchestration/stage_symbol_execution.py`
  - `tools/orchestration/stage_portfolio.py`
- `tools/orchestration/pipeline_stages.py` is now dispatcher-only.
- No stage-to-stage calls introduced; coordination remains `run_pipeline.py -> pipeline_stages.py -> stage module`.
