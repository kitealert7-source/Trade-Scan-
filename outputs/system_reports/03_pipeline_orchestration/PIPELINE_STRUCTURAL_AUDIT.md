# Pipeline Structural Audit Report — Sandbox-to-Candidate Lifecycle

**Date**: 2026-03-14  
**Subject**: Structural Sanity Audit of TradeScan Research Pipeline  
**Status**: **ALL CONTRACTS PASSED**

---

## 1. Pipeline Termination Boundary
**Goal**: Confirm `run_pipeline.py` stops at the sandbox artifact generation boundary.

- **Findings**:
    - `run_pipeline.py` (Line 551) explicitly returns after Stage-3A completion: `Candidate generation complete. Pipeline stopping at research boundary.`
    - No invocation of `run_portfolio_and_post_stages`, `filter_strategies`, or `robustness` observed in the primary execution loop.
    - `run_pipeline.py` responsibility ends strictly at Stage-3 aggregation and sandbox manifest binding.
- **Verdict**: **PASS**
- **Note**: The docstring in `run_pipeline.py` (Line 18) mentions Stage-4 as part of the orchestrator's purpose. This is a minor documentation drift and does not affect structural integrity.

## 2. Candidate Promotion Gate
**Goal**: Verify `tools/filter_strategies.py` uses relaxed criteria and follows "Registry-First" migration.

- **Findings**:
    - Relaxed criteria (TR >= 40, PF >= 1.05, R/DD >= 0.6, Exp >= 0, Sharpe >= 0.3, DD <= 80%) correctly implemented (Line 56).
    - **Registry-First**: Registry tier update (`tier: candidate`) is persisted (Line 91) *before* `shutil.move` is attempted.
    - **Idempotency**: Existing candidates are skipped (Line 86), and `shutil.move` includes a `not dest_path.exists()` check.
- **Verdict**: **PASS**

## 3. Registry Authority
**Goal**: Confirm `run_registry.json` is the single authoritative lifecycle ledger.

- **Findings**:
    - `tools/system_registry.py` contains the authoritative load/save/reconcile logic.
    - Lifecycle state (tier/status) is purely derived from registry keys.
    - No tools (Run/Cleanup/Filter) derive lifecycle state from Excel sheets or filesystem structure alone.
- **Verdict**: **PASS**

## 4. Auto-Repair Reconciliation
**Goal**: Verify the "Registry Tier == Candidate + Sandbox Folder" relocation rule.

- **Findings**:
    - `reconcile_registry()` (Line 167) contains the auto-repair rule: `if data.get("tier") == "candidate" ... src = RUNS_DIR ... dst = CANDIDATES_DIR ... shutil.move`.
    - This ensures that if a promotion was registry-persisted but folder-migration failed, the next startup sweep fixes the physical location.
    - The operation is deterministic and safe.
- **Verdict**: **PASS**

## 5. Cleanup Safety
**Goal**: Confirm `cleanup_reconciler.py` protects critical directories and only deletes sandbox runs.

- **Findings**:
    - Deletion targets are limited to `tier == sandbox` and `status == complete` AND `run_id not referenced` (Line 53).
    - `is_path_safe` (Line 73) explicitly forbids deletion of `strategies/`, `candidates/`, `registry/`, `tools/`, and `data_access/`.
    - Physical cleanup scope is restricted to `runs/` and `backtests/`.
- **Verdict**: **PASS**

## 6. Workflow Isolation
**Goal**: Verify `execute-directives.md` terminates mandatory flow at Step 11.

- **Findings**:
    - Step 11 is the **Candidate Promotion Gate** (`tools/filter_strategies.py`).
    - Robustness and deep research (Appendix) are explicitly excluded from the mandatory 1-13 sequence.
    - No automatic execution chains from Stage-3 to Robustness are present in the workflow.
- **Verdict**: **PASS**

---

## Conclusion
The TradeScan research pipeline architecture is structurally sound and strictly follows the **Registry-First** lifecycle model. The Sandbox-to-Candidate boundary is enforced both at the tool layer and the orchestration layer.

**Audit conducted by**: Antigravity (AI Architect)
