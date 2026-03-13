# ENGINE VALIDATION AUDIT REPORT

## 1. Stage-Level Validation

| Stage | Preconditions Checked | Schema Enforced | State Validation | Failure Mode | Code Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 1** | Directive, Broker Spec, Market Data | Broker Spec (Partial) | `PipelineStateManager` | **Hard Fail** | `tools/run_stage1.py` |
| **Stage 3** | Metadata, Trade Report, Master Filter | `REQUIRED_METRICS` Keys | `Pipeline`/`Directive` | **Hard Fail** | `tools/stage3_compiler.py` |
| **Portfolio** | Master Filter, Trade CSVs | Master Sheet Columns | N/A | **Hard Fail** | `tools/portfolio_evaluator.py` |

*   **Critical Gap**: `parse_directive` (pipeline_utils.py) parses text but enforces **no schema** on Directive fields (e.g. `Strategy`, `Symbol`).

## 2. Strategy Validation

| Check | Validated? | Details | Code Reference |
| :--- | :--- | :--- | :--- |
| **Logic** | ❌ NO | No check for `check_entry`/`check_exit` return types. | `execution_loop.py` |
| **Indicators** | ❌ NO | `prepare_indicators` called without validation. | `execution_loop.py` |
| **Parameters** | ❌ NO | No bounds checking (e.g. `stop_loss < 0`). | `main.py` |
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
*   **Verification**: ❌ **None**. No tool verifies `manifest_hash` before execution.
*   **Immutability**: ⚠️ **Weak**. Snapshot script deletes (`rmtree`) target directory before writing. It enforces a "Fresh Write" but not "Read-Only" protection.
*   **Artifact Overwrite**: **Protected** (Ledger is Append-Only).

## 6. Input Validation Layer

*   **Directives**: ❌ **None**. `pipeline_utils.parse_directive` accepts any Key-Value pair.
*   **Broker Specs**: ⚠️ **Minimal**. Checks `contract_size`, `min_lot` presence. No type checking.
*   **YAML**: Not used for logic, only config.

## 7. Failure Mode Classification

*   **Hard Fail (Safe)**:
    *   Missing input files (Directive, Spec, Data).
    *   State transition violations.
    *   Duplicate Run IDs or Portfolio IDs.
    *   Missing `results_tradelevel.csv`.
*   **Soft Fail (Warning)**:
    *   Missing metrics in `extract_performance_metrics` (printed as warning, but Stage 3 compiler eventually hard fails).
*   **Silent Fail (Risk)**:
    *   Strategy logic errors (infinite loops, invalid signals).
    *   Capital mismatch between assumption (5000) and reality.
    *   Directive typos (e.g. `Symblo: EURUSD` would be ignored).

## Critical Gaps Identified

1.  **Directive Schema**: No validation of directive file structure.
2.  **Hash Verification**: Code is hashed during snapshot, but never verified before run.
3.  **Strategy Logic**: Engine blindly trusts strategy code outputs.
