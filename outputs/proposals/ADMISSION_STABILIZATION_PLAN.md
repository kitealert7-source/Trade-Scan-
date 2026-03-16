# Implementation Plan: Gating & Admission Stabilization

This plan outlines a minimal-complexity upgrade to stabilize the TradeScan directive admission process, resolve sweep registry friction during retries, and clarify the operator workflow.

## 1. Current System Behavior Summary

The system currently uses a triple-gate admission flow:
1. **Stage -0.25 (Canonicalizer)**: Enforces YAML structure.
2. **Stage -0.30 (Namespace Gate)**: Enforces naming and registry binding.
3. **Stage -0.35 (Sweep Gate)**: Reserves sweep IDs and ensures research uniqueness via signature hashing.

**Friction points identified:**
- Sweep gate blocks retries if the directive hash changes (e.g., after a fix for a failed run).
- Manual creation often bypasses validation until the full pipeline is initiated.
- Gate order inconsistencies in older implementations caused invalid directives to reserve sweep names.

---

## 2. Risk Analysis

| Change | Risk | Mitigation |
| :--- | :--- | :--- |
| **Gate Reordering** | Low - Downstream stages might expect specific side effects. | Ensure `AdmissionStage` in `admission_controller.py` is the sole entry point. |
| **Retry-Safe Sweep** | Medium - Could accidentally allow overwriting a successful run. | Strict status check: Allow overwrite ONLY if status is `failed`, `invalid`, or `interrupted`. |
| **INBOX Workflow** | Low - Adds a folder, but doesn't change FSM logic. | Maintain `ACTIVE` as the authoritative source for `run_pipeline.py`. |

---

## 3. Step-by-Step Implementation Plan

### Phase 1: Gate Refinement
1.  **Gate Order Enforcement**: Ensure `tools/orchestration/admission_controller.py` strictly follows the order: `Canonicalizer` &rarr; `Namespace Gate` &rarr; `Sweep Gate`. The orchestrator must be the sole caller of these gates.
2.  **Logic Decoupling**: Remove any duplicate validation calls from inside `sweep_registry_gate.py` to ensure it only handles registry reservation.

### Phase 2: Retry-Safe Sweep Registry
1.  **Registry Integration**: Update `tools/sweep_registry_gate.py` to import `_load_registry` from `system_registry`.
2.  **Atomic Mutability (Critical)**:
    - Protect all read-modify-write operations on `sweep_registry.yaml` with a file lock inside `sweep_registry_gate.py`.
    - Flow: *Acquire lock -> Load registry -> Validate reclaim conditions -> Update entry -> Write registry -> Release lock*.
3.  **Smart Idempotency & Reclaim (Retry-Safe Sweep Registry)**:
    - If a hash mismatch occurs on a reserved sweep slot:
        - Check `run_registry.json` for any runs associated with the *existing* owner (directive_name).
        - Allow reclaim when ALL previous runs for the directive are `FAILED`, `INVALID`, `ABORTED`, or `INTERRUPTED`.
        - Block reclaim when ANY run is `COMPLETE`. This preserves research uniqueness while allowing execution retries.
4.  **Attempt Tracking & Logging**:
    - Add an optional `attempt` field to the sweep registry entry (e.g. `attempt: 2`).
    - Increment this counter ONLY when successfully reclaiming a failed slot.
    - No schema migration required; omit the field if absent.
    - Explicitly log reclaim events for audit trails and debugging: `SWEEP_RECLAIM | directive=<name> | attempt=<n> | previous_status=<status>`.

### Phase 3: Admission Workflow & Linter
1.  **Infrastructure**: Create `backtest_directives/INBOX/` directory.
2.  **New Tool: `tools/directive_linter.py`**:
    - Implements a standalone CLI that wraps `tools.orchestration.admission_controller.AdmissionStage`.
    - Operates by calling the identical admission flow used by the orchestrator (Canonicalizer &rarr; Namespace &rarr; Sweep). No duplicated validation logic.
    - Modes: `--check` (report only) and `--admit` (check + atomic move from `INBOX` to `ACTIVE`).
    - **Canonicalization Diff Approval**: When structural drift is detected, the linter must display the unified diff, write the corrected YAML to `/tmp`, and require explicit operator input (e.g., typing `APPROVED`). Only after approval will the corrected directive replace the original.
    - **Atomic Directive Admission**: The `--admit` flag must use an atomic operation (`Path.replace()`) to move the validated directive (`INBOX/file` &rarr; `ACTIVE/file`). This prevents race conditions where the pipeline might scan a partially-written file.
3.  **ACTIVE Bypass Guard**:
    - Add a lightweight guard in `tools/run_pipeline.py`.
    - If a directive appears in `ACTIVE` but was not admitted via the sweep registry, emit an observability warning: `DIRECTIVE_NOT_ADMITTED | directive=<name>`.
    - This must NOT block execution, it is for observability only.
4.  **Operator SOP**: Update docs to recommend `INBOX` &rarr; `Linter` &rarr; `ACTIVE` flow.

---

## 4. Required Code Areas to Modify

- `tools/orchestration/admission_controller.py`: Adjust gate calling sequence and error handling. Export `AdmissionStage` cleanly for linter use.
- `tools/sweep_registry_gate.py`: Implement file lock around registry writes, smart hash reclamation based on run status, and optional `attempt` incrementing with `SWEEP_RECLAIM` logging.
- `tools/run_pipeline.py`: Add the `DIRECTIVE_NOT_ADMITTED` warning observability guard.
- `tools/directive_linter.py`: [NEW] Create this tool to wrap the exact `AdmissionStage` logic and perform atomic `Path.replace()` moves.

---

## 5. Backward Compatibility Strategy

- **Registry Format**: No changes to `sweep_registry.yaml` schema; we only change the *conditions* under which an entry can be updated.
- **Existing Folders**: The system will continue to watch `active/`. The `INBOX` is an optional upstream stage for human safety.
- **Legacy Hashes**: Maintain the 16-char vs 64-char hash prefix matching implemented in `sweep_registry_gate.py`.

---

## 6. Validation and Testing Plan

1.  **Gate Order Test**: Malform a directive's YAML and verify it fails at -0.25 (Canonicalizer) before it ever hits the Sweep registry.
2.  **Retry Simulation & Tracking**:
    - Run a directive that fails during Stage-1.
    - Modify the directive (changing its hash).
    - Verify `sweep_registry_gate` allows the update because the previous run failed.
    - Verify the `attempt` counter increments in `sweep_registry.yaml`.
    - Verify the `SWEEP_RECLAIM` log is emitted.
3.  **Concurrency / Locking Test**:
    - Invoke the `directive_linter.py` simultaneously in two processes for the same sweep name.
    - Verify the file lock prevents corruption and serializes the writes.
4.  **Success Protection**:
    - Run a directive to `COMPLETE`.
    - Attempt to re-run the same sweep name with a different hash.
    - Verify the gate blocks it as a collision.

---

## 7. Directive Admission Workflow

The final, documented lifecycle mapping the operator's path to FSM states:

```
Operator
   ↓
INBOX
   ↓
directive_linter.py
   ↓
AdmissionStage
   ↓
Canonicalizer
   ↓
Namespace Gate
   ↓
Sweep Gate
   ↓
ACTIVE
   ↓
Pipeline FSM
   ↓
ACTIVE_BACKUP
   ↓
COMPLETED
```

---

## 8. What This Plan Will Fix

Upon successful implementation, the system will exhibit the following improvements:
- **Namespace failures decrease**: Errors like `NAMESPACE_PATTERN_INVALID` and `NAMESPACE_ALIAS_FORBIDDEN` will be caught early in the INBOX.
- **Retry failures disappear**: Errors such as `SWEEP_IDEMPOTENCY_MISMATCH` blockages will no longer occur for failed runs, allowing safe re-execution.
- **Clean Operator Workflow**: The pipeline feeding mechanism becomes disciplined: `INBOX` &rarr; `Linter` &rarr; `ACTIVE` &rarr; `Pipeline`.

---

## 9. Rollback Strategy

1.  Revert `sweep_registry_gate.py` to the strict idempotency version.
2.  Directives in `INBOX` can be manually moved back to `active/` if the linter flow is problematic.
3.  No repository or state corruption is expected as the changes are logic-only gates.
