# Orchestration Contract (State-Gated Pipeline)

**Status:** Authoritative runtime contract  
**Scope:** `tools/run_pipeline.py` and `tools/orchestration/*`

## 1. Control Flow Topology

Mandatory call chain:

1. `tools/run_pipeline.py`
2. `tools/orchestration/pipeline_stages.py` (dispatcher only)
3. One phase module per stage:
   - `stage_preflight.py`
   - `stage_symbol_execution.py`
   - `stage_portfolio.py`

Rules:
- Stage modules must not call each other.
- `pipeline_stages.py` coordinates stage dispatch only.
- Runtime debate/architecture notes are out-of-band and belong in documentation.

## 2. Stage Responsibilities

- `stage_preflight.py`
  - preflight execution
  - semantic validation and coverage checks
  - provision-only early stop
- `stage_symbol_execution.py`
  - per-symbol execution gates
  - stage-1 -> stage-3A run progression
  - symbol-level artifact binding/manifesting
- `stage_portfolio.py`
  - portfolio gate and ledger validation
  - post-stage non-authoritative reporting/wrapper/profile checks

## 3. State Ownership

- Run-level state: `PipelineStateManager` (`TradeScan_State/runs/<RUN_ID>/run_state.json`)
- Directive-level state: `DirectiveStateManager` (`TradeScan_State/runs/<DIRECTIVE_ID>/directive_state.json`)
- Transition mediation: `tools/orchestration/transition_service.py`
- Registry-level execution state: `TradeScan_State/registry/run_registry.json`
  - run states: `PLANNED`, `RUNNING`, `COMPLETE`, `FAILED`
  - registry is authoritative for executable unit planning/claiming

## 4. Failure/Pause Contract

- Stage modules must raise typed pipeline errors; they must not terminate process.
  - `PipelineAdmissionPause`: clean pause, exit code `0`
  - `PipelineExecutionError`: fatal failure, exit code `1` with cleanup policy
- Top-level mapping and cleanup decisions occur in:
  - `tools/run_pipeline.py::map_pipeline_error(...)`

## 5. Execution Adapter Contract

- Shell command execution is centralized in:
  - `tools/orchestration/execution_adapter.py::run_command(...)`
- Orchestrator passes this adapter into stage modules; stage modules do not own process policy.

## 6. Run Planning and Worker Claiming

- `tools/orchestration/run_planner.py` converts directives into independent runs (one per strategy/symbol).
- Planning writes/merges registry entries before execution.
- Workers claim `PLANNED` runs from registry, move them to `RUNNING`, then finalize as `COMPLETE` or `FAILED`.
- On resume, interrupted `RUNNING` entries are re-queued to `PLANNED`.

## 7. Test Invariants

Regression tests must preserve:
- resume behavior
- provision-only rerun/reset behavior
- failed -> reset guard behavior
- multi-symbol partial failure behavior
- golden log stability for control-flow-critical messages
