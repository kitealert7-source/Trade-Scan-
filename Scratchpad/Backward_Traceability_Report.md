# Backward Traceability From Strategy Master Sheet

## 1. Master Sheet Primary Key

*   **Primary Key Column:** `run_id` (Column A)
*   **Characteristics:**
    *   **Globally Unique:** Yes (SHA-256 Hash or UUID).
    *   **Immutable:** Yes. Generated at execution time and never modified.

## 2. Run → Artifact Mapping

For a single row in the Strategy Master Sheet, the following filesystem paths are strictly mapped:

| Master Sheet Column | Derived Path | Classification |
| :--- | :--- | :--- |
| `strategy` (Col B) | `backtests/<strategy>/` | **Authoritative (Run Output)** |
| `run_id` (Col A) | `strategies/<run_id>/` | **Authoritative (Strategy Persistence)** |
| `strategy` (Col B) | `backtests/<strategy>/metadata/run_metadata.json` | **Authoritative (Identity Source)** |
| `strategy` (Col B) | `backtests/<strategy>/AK_Trade_Report_*.xlsx` | Derived (Reporting) |

*Note: `<strategy>` corresponds to the `strategy_name` in the metadata.*

## 3. Backward Trace Rules

**Deletion Logic**
Given a row `R` with `run_id` and `strategy`:

1.  **Delete Strategy Persistence:**
    *   Target: `strategies/<R.run_id>/`
    *   Action: `rm -rf`

2.  **Delete Backtest Output:**
    *   Target: `backtests/<R.strategy>/`
    *   Action: `rm -rf`
    *   *Constraint:* This folder is 1:1 with the strategy run. If the user intends to keep "history" of previous runs for the same strategy name, they must rely on the RunID-based `strategies/` folder. The `backtests/` folder represents the *latest* state of that strategy.

**Shared Artifacts (Preserve)**
*   `backtests/Strategy_Master_Filter.xlsx` (The Index itself)
*   `backtests/batch_summary_*.csv` (Batch Logs - do not delete)
*   `backtests_directives/*` (Source directives - do not delete)

## 4. Validation Checks

**Trace Integrity Checks**

| Check Type | Condition | Status |
| :--- | :--- | :--- |
| **Orphaned Row** | Row exists in Master Sheet BUT `backtests/<strategy>/` does not exist. | **Corrupt Index** (Remove Row) |
| **Orphaned Row** | Row exists in Master Sheet BUT `strategies/<run_id>/` does not exist. | **Corrupt Index** (Remove Row) |
| **Orphaned Folder** | `backtests/<strategy>/` exists BUT `run_id` (from its metadata) is not in Master Sheet. | **Unindexed Run** (Add to Index OR Delete) |
| **Orphaned Folder** | `strategies/<run_id>/` exists BUT `run_id` (from its metadata) is not in Master Sheet. | **Zombie Artifact** (Delete) |
| **Mismatched ID** | `backtests/<strategy>/metadata/run_metadata.json` has `run_id` != Master Sheet `run_id`. | **Stale Index** (Row Refers to Old Run) |

## 5. Failure Semantics

*   **Partial Artifacts:** If a deletion is interrupted (e.g., `backtests/<strategy>` gone but `strategies/<run_id>` remains), the system must treat the remaining artifacts as "Orphaned Folders" and complete the deletion on the next sweep.
*   **Cleanup Abort:** If `backtests/<strategy>/` is missing but `strategies/<run_id>/` exists, the cleanup process should **proceed** to delete `strategies/<run_id>/` and then remove the row. Do not abort.
*   **Batch Summary:** `backtests/batch_summary_*.csv` files are **excluded** from individual run cleanup. They are append-only logs and considered non-authoritative.

## 6. Constraints / Exclusions

*   **Untraceable:** Any file inside `backtests/` that does not match a known strategy folder pattern or standard artifact name.
*   **Manual Files:** Any user-created files inside strategy folders will be deleted by the `rm -rf` action.
*   **Output Folder:** `outputs/` directory is currently not linked to the Master Sheet in the `stage3_compiler.py` logic and appears unused or legacy. Traceability is **UNTRACEABLE** for `outputs/` based on current Master Sheet logic.
