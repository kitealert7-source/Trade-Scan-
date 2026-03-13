# Phase-2 Readiness Sanity Test Report

This report evaluates the TradeScan pipeline's readiness for the **Phase-2 lifecycle implementation (sandbox → candidates)**.

## Executive Summary

| Category | Status | Notes |
| :--- | :--- | :--- |
| **1. Run Container Integrity** | **PASS** | `run_pipeline.py` enforces required schema and quarantines invalid runs. |
| **2. Registry Consistency** | **PASS** | `reconcile_registry()` ensures registry/filesystem alignment; tier field supported. |
| **3. Manifest Integrity** | **PASS** | Manifests store hashes for core artifacts; startup validation enforced. |
| **4. Data Availability Gate** | **PASS** | `preflight.py` verifies existence, timeframe, and temporal coverage. |
| **5. Directive Replay Capability** | **PASS** | `run_pipeline.py --all` provides sequential replay with full guardrails. |
| **6. Path Configuration** | **WARNING** | No centralized `STATE_ROOT` exists; paths depend on `PROJECT_ROOT`. |
| **7. Lifecycle Tier Readiness** | **PASS** | Registry supports `tier` field (`sandbox`, `candidate`, `portfolio`). |
| **8. Cleanup Boundaries** | **PASS** | `cleanup_reconciler.py` implements strict physical guardrails (`is_path_safe`). |

---

## Detailed Evaluation

### 1. Run Container Integrity
The orchestrator's `enforce_run_schema` function validates the presence of `data/`, `manifest.json`, and `run_state.json`. Any run failing this test is automatically moved to `quarantine/runs/`, preventing corrupt data from entering the pipeline.

### 2. Registry Consistency
`registry/run_registry.json` serves as the authoritative ledger. The `reconcile_registry()` function at startup detects orphaned folders on disk and marks missing folders in the registry as `invalid`. This ensures a single source of truth.

### 3. Manifest Integrity
Completed run manifests include SHA256 hashes for:
- `results_tradelevel.csv`
- `results_standard.csv`
- `equity_curve.csv`
- `batch_summary.csv`
`verify_manifest_integrity` validates these hashes at startup, ensuring artifact immutability.

### 4. Data Availability Gate
The preflight agent in `governance/preflight.py` implements a multi-stage data gate that asserts both the presence of the research dataset and that the available dates fully encompass the directive's `START_DATE` and `END_DATE`.

### 5. Directive Replay Capability
The `--all` flag in `run_pipeline.py` triggers a sequential batch execution mode. This path initializes startup guardrails (schema enforcement, drift detection, registry reconciliation) before processing any directives, ensuring high-integrity replays.

### 6. Path Configuration
**Observation**: The system lacks a centralized `STATE_ROOT` identifier. Paths are currently hardcoded or derived relative to `PROJECT_ROOT`. 
**Recommendation**: While this does not block Phase-2, implementing a configurable `STATE_ROOT` would improve portability and environment isolation.

### 7. Lifecycle Tier Readiness
The `run_registry.json` schema already includes a `tier` field. Registry logic is agnostic to the string values, meaning it already supports `candidate` and `portfolio` tags. The infrastructure is ready for the promotion logic implementation.

### 8. Cleanup Boundaries
`tools/cleanup_reconciler.py` contains an `is_path_safe` validator that prevents any deletions outside of `runs/` or `backtests/`. It also explicitly forbids deletions in system-critical folders like `strategies`, `candidates`, and `registry`.

---

## Conclusion
The pipeline has passed all critical integrity and safety checks. **TradeScan is ready for Phase-2 lifecycle implementation (sandbox → candidates).**
