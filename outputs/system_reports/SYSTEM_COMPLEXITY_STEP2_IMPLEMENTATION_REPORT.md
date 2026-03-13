# System Complexity Step-2 Implementation Report
**Date:** 2026-03-12  
**Step:** Extract orchestration stages into modules

## Objective
Reduce monolithic orchestrator complexity by moving stage logic out of `tools/run_pipeline.py` while preserving behavior.

## Implemented Refactor
### 1. New stage module
- Added `tools/orchestration/pipeline_stages.py` with extracted coordinator blocks:
  - `run_preflight_semantic_checks(...)`
  - `run_symbol_execution_stages(...)`
  - `run_portfolio_and_post_stages(...)`

### 2. Coordinator wiring
- `tools/run_pipeline.py` now delegates to stage functions and remains the coordinator.
- Existing top-level error handling and fail-safe cleanup semantics were retained.

### 3. Existing transition centralization preserved
- `run_pipeline.py` and extracted stage module continue using transition service APIs (no direct `transition_to(...)` usage in these files).

## Measured Impact
- `tools/run_pipeline.py` line count:
  - Before extraction: ~999
  - After extraction: 480
- Stage logic moved to:
  - `tools/orchestration/pipeline_stages.py` (467 lines)

## Validation Evidence
Executed:
1. `python -m py_compile tools/run_pipeline.py tools/orchestration/pipeline_stages.py tools/orchestration/transition_service.py`
2. `pytest -q tests/test_transition_service.py tests/test_provision_only_integration.py tests/test_sweep_registry_hash_compat.py tests/test_strategy_provisioner_compat.py`

Result:
- `9 passed`

## Outcome
Step 2 is complete for the orchestrator path:
- stage blocks are extracted into orchestration module(s),
- coordinator is slimmer and easier to reason about,
- focused regression checks are passing.
