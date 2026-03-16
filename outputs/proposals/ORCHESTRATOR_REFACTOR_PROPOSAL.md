# Refactor Proposal: Orchestrator Registry & Runner Architecture

## Goal
Transform the TradeScan orchestrator into a **thin coordinator** by adopting a **Stage Registry + Stage Runner** architecture. This design decouples execution logic from flow control and standardizes stage interfaces while preserving identical runtime behavior.

## 1. Core Architectural Components

### A. Stage Registry
The `STAGE_REGISTRY` defines the **Execution Phase**. These stages consume a fully-formed `PipelineContext`.
*   **Property**: Deterministic and static.
*   **Execution Sequence**:
    1.  `PreflightStage`: Semantic checks, Provisioning gate.
    2.  `SymbolExecutionStage`: Stage 1 Generator (Registry worker).
    3.  `ReportingStage`: Stage 2 Compiler (Symbol-level reports).
    4.  `AggregationStage`: Stage 3 Compiler (Master ledger).
    5.  `ManifestBindingStage`: Stage 3A Entropy, Equity curves, and Manifest binding.

### B. Bootstrap Phase (Orchestrator Owned)
The following controllers run **before** context creation and are not part of the `StageRunner` loop:
1.  **AdmissionStage**: (Canonicalization, Namespace, Sweep). Required to determine strategy identity.
2.  **DirectivePlanningStage**: (Run mapping). Required to generate Run IDs and Registry paths.

### C. Stage Runner (FSM Executor)
The Stage Runner is the **sole executor of state transitions**.
*   **FSM Ownership**: Transitions remain defined in `transition_service.py`.
*   **Role**: The Runner iterates the registry and invokes stages. It performs state transitions based on stage success/failure requests.
*   **Resume/Checkpointing**: The Runner inspects the `current_state` from `PipelineContext` at startup. It will **atomically skip** stages that are already marked as COMPLETE in the FSM to ensure identical resume behavior to `run_pipeline.py v3.2`.
*   **Safety**: Stages **must not** mutate FSM states arbitrarily; they return outcomes that the Runner acts upon.

### D. PipelineContext
A unified context object passed to stages.
```python
class PipelineContext:
    directive_id: str
    directive_path: Path
    directive_config: dict (populated after Admission)
    run_ids: list[str] (populated after Planning)
    symbols: list[str] (populated after Planning)
    project_root: Path
    python_exe: str
    registry_path: Path
    provision_only: bool
```

---

## 2. Refined Execution Flow
The orchestrator follows a strict linear sequence to ensure context integrity:

1.  **Mandatory Startup Guards**: (Schema, Registry consistency, Timestamp guard).
2.  **Load Raw Directive**: Identify target file path.
3.  **AdmissionStage**: Perform canonical/namespace gates on raw file.
4.  **Parse Directive**: Call `parse_directive()` to get strategy config.
5.  **DirectivePlanningStage**: Call `plan_runs_for_directive()` to map Run IDs.
6.  **Build PipelineContext**: Finalize context with parsed config and run IDs.
7.  **StageRunner Activation**: Execute remaining stages (`Preflight` onward).

---

## 3. Structural Refactoring

### Reduced `run_pipeline.py`
The orchestrator becomes a thin wrapper for loading, planning, and triggering the Runner.

### Optional Deep Audits
Expensive checks (`verify_manifest_integrity`, `detect_strategy_drift`) are moved to a standalone `PreflightAuditor` module, separated from mandatory startup guards.

---

## 4. Safety & Behavior Constraints
I explicitly confirm that the following remain **identical and non-breaking**:
*   **Ordering**: Exact sequencing of stages (0.25 through 3A) is preserved.
*   **Directive FSM**: All states (`PREFLIGHT_COMPLETE`, etc.) remain authoritative.
*   **Registry Logic**: Registry ID generation and locking remain unchanged.
*   **Fail-Fast**: The system halts immediately upon any stage failure.

---

## 5. Migration Plan
1.  **Phase 1 (Context)**: Introduce `PipelineContext` structure.
2.  **Phase 2 (Stage Extraction)**: Move logic into passive `AdmissionStage`, `PlanningStage`, and `PreflightStage` units.
3.  **Phase 3 (Splitting Execution)**: Divide `stage_symbol_execution.py` into `Execution`, `Reporting`, and `Binding` stages.
4.  **Phase 4 (Registry & Runner)**: Initialize the `STAGE_REGISTRY` and `StageRunner` class.
5.  **Phase 5 (Coordinator Strip)**: Final reduction of `run_pipeline.py`.

---

## 6. Design Suggestions (Optional Context)
Before proceeding with implementation, I suggest considering:
*   **Stage Telemetry Delegate**: Instead of simple print statements, stages could emit events to a `TelemetryDelegate` inside the context. This facilitates future integration with logging dashboards without changing stage logic.
*   **CLI Backward Compatibility**: Ensure `run_pipeline.py` maintains its exact CLI flags (`--all`, `--provision-only`, etc.) so external CI/CD or wrapper tools do not break.
