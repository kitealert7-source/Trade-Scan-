# System Complexity Refactor Plan
**Date:** 2026-03-11  
**Scope:** Orchestration simplification and state-machine risk reduction

## 1. Baseline and Freeze Behavior (Day 1)
- Capture current outputs/logs for 3 representative directives:
  - single-symbol
  - multi-symbol
  - provision-only
- Define non-regression checks before refactor.
- Primary files:
  - `tools/run_pipeline.py`
  - `tools/pipeline_utils.py`
  - `governance/preflight.py`

## 2. Extract Orchestration Stages into Modules (Days 2-4)
- Move stage blocks from `tools/run_pipeline.py` into `tools/orchestration/stage_*.py`.
- Keep `run_pipeline.py` as coordinator only (argument parsing + stage sequencing).

## 3. Centralize All State Transitions (Days 5-6)
- Create one transition service (single API) and remove scattered direct `transition_to()` calls.
- Add guard helpers:
  - advance only
  - no regression
  - idempotent no-op

## 4. Separate Migration/Provision Pipeline from Execution Pipeline (Days 7-8)
- Pull auto-migration/provision-only path into dedicated pre-exec workflow.
- Ensure execution starts only after directive identity is finalized.

## 5. Simplify Error Handling Model (Day 9)
- Replace deep `try/except` branching with typed pipeline errors and one top-level failure mapper.
- Standardize failure actions for run-level and directive-level states.

## 6. Harden Tests Around State-Machine Invariants (Days 10-11)
- Add scenario tests for:
  - resume
  - provision-only rerun
  - failed -> reset
  - multi-symbol partial failures
- Add golden-output tests so logs/outputs remain consistent.

## 7. Documentation and Operating Contract Update (Day 12)
- Document the orchestration contract and state transition rules.
- Update go-live audit section to reflect simplified control flow.

## Success Criteria
1. `tools/run_pipeline.py` reduced to less than 500 lines.
2. Direct state transition calls in orchestrator reduced to near-zero (service-mediated).
3. Provision-only + resume flows pass deterministically across repeated runs.
4. Existing critical tests pass, plus new invariant tests.
