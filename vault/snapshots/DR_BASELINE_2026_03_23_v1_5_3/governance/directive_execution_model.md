# Directive Execution Model

## Current Model
- One directive can contain multiple symbols.
- Run IDs are generated per symbol via `generate_run_id(...)`.
- Orchestrator owns directive-level and run-level state transitions.
- Directive execution units are persisted in `TradeScan_State/registry/run_registry.json`.

## Practical Implication
- `run_pipeline.py` plans runs first, writing registry entries (`PLANNED`).
- Worker logic claims planned runs (`RUNNING`) and finalizes each unit (`COMPLETE`/`FAILED`).
- `run_pipeline.py` initializes one directive state and multiple run states.
- Stage execution remains coordinated from orchestrator entry points.

## Why This Exists
- Existing stage tooling emits artifacts in a symbol-scoped layout.
- State gating and audit requirements operate at both directive and run scopes.

## Runtime Contract
- Runtime code should implement the model, not debate alternatives inline.
- Architectural discussion belongs in this document, not orchestration execution paths.
