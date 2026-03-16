# SOP_CLEANUP.md (v2.1)

## 1. Purpose

This SOP defines how strategy-related artifacts are **retained, overwritten, and cleaned up** using a **Registry-First Authority Model**.

- The **System Registry** (`run_registry.json`) is the **sole authoritative ledger** for determining run validity and retention.
- The filesystem is used for state alignment and physical execution containers.
- Excel artifacts and UI reports are **derived observations** and have no governance authority over cleanup decisions.

---

## 2. Authority Hierarchy

The system follows a strict hierarchy for determining what "exists" and what is "valid":

1. **Authoritative Layer (Primary Authority)**
   - `TradeScan_State/registry/run_registry.json`
   - `TradeScan_State/runs/<run_id>/` (Atomic Execution Artifacts)
   - `TradeScan_State/candidates/<run_id>/` (Promoted Authoritative Runs)

2. **Derived / Computation Layer (Non-Authoritative)**
   - `TradeScan_State/sandbox/Strategy_Master_Filter.xlsx`
   - `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
   - `AK_Trade_Report.xlsx`

3. **UI / Research Layer (Disposable)**
   - `TradeScan_State/backtests/` folders (Disposable reporting views)
   - Research Summary reports

---

## 3. Folder Role Definitions

| Directory | Role | Description |
| :--- | :--- | :--- |
| **`runs/`** | **Authoritative (Sandbox)** | Holds execution artifacts for runs in the `sandbox` tier. |
| **`candidates/`** | **Authoritative (Promoted)** | Holds execution artifacts for runs promoted to the `candidate` tier. |
| **`backtests/`** | **Disposable UI View** | Materialized reporting views for human consumption. Safely deletable if not registered. |
| **`sandbox/`** | **Aggregation Workspace** | Temporary staging area for master filter generation. |

---

## 4. Cleanup Invariants (Registry Authority)

### Authoritative Ledger

- `TradeScan_State/registry/run_registry.json` is the **sole authority** for historical run retention.

### Valid Run Definition

- A run is valid if and only if it is indexed in the System Registry with a status of `complete`.

### Zombie Definition

- Any folder in `runs/` or `candidates/` that is **not** present in the System Registry is a zombie and must be deleted.
- Any folder in `backtests/` that does not correspond to an active `run_id` in the registry is a disposable orphan.

### Excel Independence

- Excel artifacts (e.g. `Strategy_Master_Filter.xlsx`) **must never be used as authority** for cleanup or maintenance decisions. They are derived metrics summaries.

---

## 5. Maintenance & Reconciliation Procedure

### 5.1 Reconciliation (Alignment)

The system enforces consistency between the registry and disk via `reconcile_registry()`.

- Physically present folders missing from the registry are injected as `sandbox` orphans.
- Registered runs missing physical data are marked as `invalid`.

### 5.2 Cleanup Workflow (Safe Execution)

To maintain workspace hygiene, the following workflow is mandated:

1. **Dry Run**: `python tools/cleanup_reconciler.py`
   - Review the planned deletions and flagged paths.
2. **Review**: Ensure no authoritative candidate runs are incorrectly flagged.
3. **Execute**: `python tools/cleanup_reconciler.py --execute`
   - Deletes zombie runs and orphaned UI views.

---

## 6. Prohibitions

- **Inviolable Artifacts**: The `cleanup_reconciler` MUST NEVER delete:
  - `TradeScan_State/registry/run_registry.json`
  - `TradeScan_State/candidates/<run_id>/` folders
- **Governed Lifecycle**: Authority artifacts must only change through authorized lifecycle tools (e.g., promotional filters or registry management scripts).
- **No Manual Deletion**: All cleanup must be driven by the reconciler to ensure registry synchronization.
- **No Excel Authority**: Do not use "deleting a row in Excel" as a method for artifact cleanup. Artifacts must be removed via registry/reconciler logic.
- **No Retention of Invalids**: Runs marked as `invalid` or missing core artifacts (`manifest.json`, etc.) should be purged during the next maintenance cycle.

---

## 7. Guarantees

When enforced, this hierarchy ensures:

- **Registry Integrity**: The registry and disk are always synchronized.
- **Disposable UI**: The `backtests/` directory remains clean and contains only views relevant to registered runs.
- **Audit-Safe**: Deletions are logged and follow a deterministic, ledger-authoritative path.
