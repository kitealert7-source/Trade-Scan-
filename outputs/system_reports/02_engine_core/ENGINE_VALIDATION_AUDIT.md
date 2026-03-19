# ENGINE VALIDATION AUDIT REPORT

## 1. Stage-Level Validation

| Stage | Preconditions Checked | Schema Enforced | State Validation | Failure Mode | Code Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 0** | Schema, YAML structure | Full Admission Schema | INBOX to ACTIVE | **Hard Fail** | `tools/directive_linter.py` |
| **Stage 1** | Directive, Broker Spec, Market Data | Validated `ACTIVE` Directive | `PipelineStateManager` | **Hard Fail** | `tools/run_stage1.py` |
| **Stage 3** | Metadata, Trade Report, Master Filter | `REQUIRED_METRICS` Keys | `Pipeline`/`Directive` | **Hard Fail** | `tools/stage3_compiler.py` |
| **Portfolio** | Master Filter, Trade CSVs | Master Sheet Columns | N/A | **Hard Fail** | `tools/portfolio_evaluator.py` |

*   **Admission Gap Resolved**: Previously `parse_directive` lacked schema validations. In v1.5.3, the Governance Layer (`directive_linter.py` and `semantic_validator.py`) strictly enforces the directive schema *before* allowing `ACTIVE` status.

## 2. Strategy Validation

| Check | Validated? | Details | Code Reference |
| :--- | :--- | :--- | :--- |
| **Logic** | ✅ YES (AST) | Lexical scans ensure `check_entry` and `check_exit` structure. | `tools/semantic_validator.py` |
| **Indicators** | ✅ YES | Parameters cross-compared with active strategy attributes. | `tools/semantic_validator.py` |
| **Parameters** | ✅ YES | Evaluated during parsing and preflight execution dry-runs. | `tools/exec_preflight.py` |
| **Data Columns** | ⚠️ PARTIAL | Checks `close` exists; `high`/`low` fallback. | `execution_loop.py` |
| **Timeframe** | ✅ YES | Filters data by `START_DATE`/`END_DATE`. | `run_stage1.py` |

## 3. Data Integrity Checks

*   **Timestamps**: **Enforced**. `load_market_data` sorts by timestamp and drops duplicates. (`run_stage1.py`)
*   **NaN/Inf**: **Partial**. `normalize_pnl_to_usd` handles zero-division. `portfolio_evaluator` replaces 0 with NaN for Sharpe.
*   **Run ID Duplication**: **Enforced**. `portfolio_evaluator` explicitly checks for duplicate run_ids in Backtests root. (**Hard Fail**)
*   **Symbol Duplication**: **Enforced**. `load_all_trades` prevents loading same run_id twice.

## 4. Portfolio-Level Checks

*   **Capital Consistency**: ❌ **Silent**. Uses hardcoded `CAPITAL_PER_SYMBOL = 5000.0`. Does not verify if actual run used this capital.
*   **Concurrency**: ✅ **Computed**. Calculated post-facto. No runtime guard (Stage 1 is isolated).
*   **Ledger Duplication**: ✅ **Guarded**. `update_master_portfolio_ledger` raises ValueError if `portfolio_id` exists. (**Hard Fail**)
*   **Divide-by-Zero**: ✅ **Guarded**. `compute_portfolio_metrics` handles Sharpe/Sortino/max_dd denominators.

## 5. Hash & Snapshot Integrity

*   **Computation**: `sha256` of file content (`tools/create_audit_snapshot.py`).
*   **Verification**: ✅ **YES**. `verify_engine_integrity.py` hashes the engine components at runtime *before* every execution.
*   **Immutability**: ⚠️ **Weak**. Snapshot script deletes target directory before writing enforcing "Fresh Write", but true "Read-Only" requires OS-level permissions.
*   **Artifact Overwrite**: **Protected** (Ledger is Append-Only).

## 6. Input Validation Layer

*   **Directives**: ✅ **Strict**. `directive_linter.py` evaluates all keys/types against canonical schema.
*   **Broker Specs**: ⚠️ **Minimal**. Checks `contract_size`, `min_lot` presence. No type checking.
*   **YAML**: Used recursively for deeply nested schema evaluation during linting.

## 7. Failure Mode Classification

*   **Hard Fail (Safe)**:
    *   Missing input files (Directive, Spec, Data).
    *   State transition violations.
    *   Duplicate Run IDs or Portfolio IDs.
    *   Missing `results_tradelevel.csv`.
    *   **Invalid YAML schema (Stage 0).**
*   **Soft Fail (Warning)**:
    *   Missing metrics in `extract_performance_metrics` (printed as warning, but Stage 3 compiler eventually hard fails).
*   **Silent Fail (Risk)**:
    *   Capital mismatch between assumption (5000) and reality.

## Critical Gaps Identified (Updated)

1.  **Directive Schema**: (RESOLVED) Validation is now strictly enforced by the `directive_linter.py`.
2.  **Hash Verification**: (RESOLVED) Handled automatically by `verify_engine_integrity.py`.
3.  **Strategy Logic**: Engine still relies heavily on implicit returns from strategies (e.g., `check_entry()`), but semantic preflight has greatly reduced risk.

*Note: With the addition of the Stage 0 Governance Gates, System Data Integrity operates at an expected confidence degree for initial production deployment.*
