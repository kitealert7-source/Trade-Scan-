# Orchestrator Audit Report: TradeScan Pipeline

## 1. Executive Summary
The logic in `tools/run_pipeline.py` and its supporting `orchestration/` modules has become fragmented over time. While the system is robust, the current structure has several "complexity hotspots" and redundancies that increase operational friction and make maintenance difficult.

## 2. Identified Redundancies
*   **Overlapping Admission Gates**: `run_pipeline.py` performs manual "Stage -0.25" through "Stage -0.35" checks (Canonicalization, Namespace, Sweep) which now overlap with the new **Workflow Step 0** (Manual Pre-checks). 
*   **Redundant Startup Guardrails**: The main `main()` function in `run_pipeline.py` runs several expensive startup checks (`verify_manifest_integrity`, `enforce_run_schema`, `gate_registry_consistency`) every time it starts, even if only running a single directive.
*   **Duplicate Registry Reconciliation**: `gate_registry_consistency()` and `reconcile_registry()` are called consecutively in `main()`, both performing similar filesystem-to-registry scans.

## 3. Complexity Hotspots
*   **`run_pipeline.py` Monolith**: The `run_single_directive` function contains deep logic for YAML parsing, structural drift detection, and early-stage gating that should be encapsulated.
*   **`stage_symbol_execution.py` Congestion**: This module manages Stage-1 (Generation), Stage-2 (Compilation), and Stage-3 (Aggregation), including the complex "Binding" logic for manifests and hashes. This violates the principle of single responsibility.
*   **Static Guardrails**: Expensive checks like `verify_manifest_integrity` (which hashes artifacts for all runs) should be optimized or moved to an as-needed "Audit Mode."

## 4. Stage Boundary Issues
*   **Inconsistent Numbering**: Stages alternate between floating-point numbers (-0.25, -0.30) and integer phases (Stage 1, 2, 3), leading to confusion in the logging and state tracking.
*   **Fragmented Error Logic**: Error mapping is split between `map_pipeline_error` in the entry point and various `try-except` blocks in the stage controllers, making it difficult to follow the "Best-Effort" cleanup flow.

## 5. Risk Assessment
The current structural problems do not affect output correctness (the pipeline remains deterministic), but they pose a risk to **performance scalability** and **code maintainability**.
