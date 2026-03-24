# State Lifecycle Management Workflow: Lineage-Aware Cleanup

## 1. Workflow Design

### Stage 1: Lineage Extraction (Build `KEEP_RUNS`)
*   **Purpose:** Mathematically define the absolute bounding box of all actively referenced `run_id`s in the system.
*   **Inputs:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`, `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx`.
*   **Outputs:** A unified, deduplicated array of strings (`KEEP_RUNS`).
*   **Actions Performed:** Parse the active spreadsheets. Extract the exact ID strings from `constituent_run_ids` and `run_id` columns. Normalize and merge them into a single validation set.
*   **Failure Conditions:** Abort if either input file is missing, corrupted, or unreadable.

### Stage 1B: Referential Integrity & Validation Check (MANDATORY)
*   **Purpose:** Enforce absolute system consistency before permitting any scan or dry run.
*   **Inputs:** `KEEP_RUNS` array, `Master_Portfolio_Sheet.xlsx`.
*   **Actions Performed & Failure Conditions (Abort entire process if ANY fail):**
    1.  *Run Dependency Check:* For each `run_id` in `KEEP_RUNS`, verify that `TradeScan_State/runs/<run_id>/` exists.
    2.  *Backtest Footprint Check:* For each `run_id` in `KEEP_RUNS`, verify that a folder matching `TradeScan_State/backtests/<strategy_id>_<symbol>/` exists and contains `metadata/run_metadata.json` with a `run_id` field equal to this run_id. *(Note: backtests are stored as `{strategy_id}_{symbol}/` folders, not as `<run_id>.json` flat files — corrected 2026-03-24.)*
    3.  *Portfolio Folder Validation:* Verify every `portfolio_id` defined in `Master_Portfolio_Sheet.xlsx` exists physically as a directory in `TradeScan_State/strategies/<portfolio_id>`.

### Stage 2: Artifact Mapping & Scan
*   **Purpose:** Traverse the heavy staging directories to identify explicitly what exists vs. what is mathematically designated for deletion.
*   **Inputs:** `KEEP_RUNS` array, target staging directories (`runs`, `backtests`, `backtest_directives`).
*   **Outputs:** Two categorical lists: `paths_to_keep` and `paths_to_quarantine`.
*   **Actions Performed:** Loop linearly through target directories. Parse the filesystem names natively. Evaluate strict equality against the `KEEP_RUNS` map. **(Constraint: Extraction must be identical across sources. `abc123` != `ABC123`. `abc123.json` must strip exactly to `abc123`. Any anomaly skips deletion).**
*   **Failure Conditions:** Abort if any target core directory (`TradeScan_State/runs/`, etc.) is missing from the disk.

### Stage 3: Dry Run & Validation
*   **Purpose:** Perform a safe, non-destructive simulation of the execution block to enforce mathematical invariants before mutation.
*   **Inputs:** `paths_to_quarantine`, `paths_to_keep`.
*   **Outputs:** `dry_run_report.md` (console + artifact).
*   **Actions Performed:** 
    *   Print Sanity Tally: `total_keep_runs` vs `total_runs_found` on disk.
    *   Calculate projected grouped counts for deletion.
    *   Explicitly confirm that **no KEEP_RUNS ID appears anywhere in the delete list**.
*   **Failure Conditions:** Abort if a `KEEP_RUNS` ID is mathematically detected inside the compiled `paths_to_quarantine` (Invariant Breach).

### Stage 4: Execution (Quarantine Mode)
*   **Purpose:** Physically mutate the filesystem state by sequestering abandoned artifacts out of active processing layers.
*   **Inputs:** `paths_to_quarantine`.
*   **Outputs:** Populated `TradeScan_State/quarantine/` directory.
*   **Actions Performed:** Utilizing `shutil.move`, migrate every path listed in `paths_to_quarantine` from its origin directory to a timestamped subfolder inside `quarantine/`. 
*   **Failure Conditions:** Abort and log if OS-level filesystem permissions deny a move operation.

### Stage 5: Post-Cleanup Verification & Reporting
*   **Purpose:** Prove systemic integrity. 
*   **Inputs:** Resulting mutated directories.
*   **Outputs:** `cleanup_report.json`.
*   **Actions Performed:** Tally final physical disk counts. Generate the JSON report object. Optionally trigger a silent portfolio evaluation to ensure required fallback documents (`Strategy_Master_Filter.xlsx`) were not moved.
*   **Failure Conditions:** Log warning if final disk counts do not exactly match the projected `paths_to_keep` counts.

---

## 2. Artifact Mapping

| Target Directory | Content Artifacts | ID Derivation Rule | Link to `KEEP_RUNS` | Action Category |
| :--- | :--- | :--- | :--- | :--- |
| `Trade_Scan/backtest_directives/` | `.txt` instruction files | Parse file string to strictly map back to a corresponding `run_id` | Must exist inside `KEEP_RUNS` | **Prune if `run_id` reliably extracted AND not in `KEEP_RUNS`. Otherwise skip.** |
| `TradeScan_State/runs/` | Deep folders containing `strategy.py`, `results.csv` | Exact Folder Name equals absolute `run_id` | Must exist inside `KEEP_RUNS` | **Prune if missing** |
| `TradeScan_State/backtests/` | `{strategy_id}_{symbol}/` folders containing `raw/`, `metadata/run_metadata.json`, `portfolio_evaluation/` | `run_metadata.json → run_id` field maps to `KEEP_RUNS` entry *(not filename — corrected 2026-03-24)* | Must exist inside `KEEP_RUNS` | **Prune if missing** |
| `TradeScan_State/sandbox/` | `Strategy_Master_Filter.xlsx` | N/A (Static fallback mapping) | Relied upon universally by evaluation scripts | **MANUAL RETAIN ALL** |
| `TradeScan_State/candidates/` | `Filtered_Strategies_Passed.xlsx` | N/A (Active Source) | Feeds `KEEP_RUNS` natively | **MANUAL RETAIN ALL** |
| `TradeScan_State/strategies/` | Portfolio deployment folders | Exact Folder Name equals absolute `portfolio_id` | Must exist as an active `portfolio_id` in Master Sheet | **Prune abandoned Portfolios** |

---

## 3. `KEEP_RUNS` Construction Logic

**Formula:**
`KEEP_RUNS` = `[run_id FROM candidates]` ∪ `[split(constituent_run_ids) FROM strategies]`

**Parsing Rules:**
1.  **Candidates Extraction:** Read `Filtered_Strategies_Passed.xlsx`. Extract absolute values from the `run_id` column.
2.  **Master Extraction:** Read `Master_Portfolio_Sheet.xlsx`. Target `constituent_run_ids` column. Delimiter is `,`. Split the cell, iterate tokens.

**Normalization Rules:**
*   String Casting: Force `str(x)` immediately upon extraction.
*   Whitespace Stripping: Apply `.strip()` to drop hidden spaces or newlines (e.g. ` " id " ` -> `"id"`).
*   Structure: Cast final list through Python `set()` mathematically to forcefully drop duplicates.

**Edge Cases:**
*   Blank cells (`NaN`, `None`, empty string) are skipped.
*   Single-run constituent strings do not contain commas; they are caught natively by `split(',')` operating as a single-element array.

---

## 4. Safety & Invariants

**Strict Invariants:**
1.  No artifact explicitly linked to `KEEP_RUNS` is ever moved, modified, or deleted.
2.  All `run_ids` securely resting in `KEEP_RUNS` must possess required artifacts (`runs/<id>/`, and a `backtests/{strategy_id}_{symbol}/metadata/run_metadata.json` where the `run_id` field matches). *(corrected 2026-03-24 — backtests are folder-based, not flat .json files)*
3.  Active portfolio subfolders must exactly shadow active `portfolio_ids` defined in the Master Sheet.

**Pre-Checks / Referential Integrity (Before Scan):**
*   Verify `Master_Portfolio_Sheet.xlsx` exists.
*   Verify `Filtered_Strategies_Passed.xlsx` exists.
*   For all elements in `KEEP_RUNS`, exact paths for `runs/<id>/` MUST pre-exist or process aborts. Backtest footprint is verified by scanning `backtests/` folders and matching the `run_id` field inside `metadata/run_metadata.json`. *(corrected 2026-03-24)*
*   Verify all Portfolio IDs mapped exist natively as root folders.

**Validation Checks (After Dry Run):**
*   Intersection of `paths_to_quarantine` array and `KEEP_RUNS` array MUST rigorously equal `0`.

---

## 5. Execution Strategy

**Phase A: DRY_RUN**
*   **Behavior:** Simulates logic silently. Iterates `os.listdir()` over all target mapping directories.
*   **Identification:** If `folder_name NOT IN KEEP_RUNS`, append to `quarantine_targets` **ONLY IF extraction perfectly matches identity bounds**.
*   **Outcome:** Generates grouped console CLI printouts.
    *   **Sanity Tally Output:**
        *   `total_keep_runs`: Integer
        *   `total_runs_found_on_disk`: Integer
    *   **Output Grouped Quarantines:**
        *   `runs_to_delete`: Integer
        *   `backtests_to_delete`: Integer
        *   `directives_to_delete`: Integer (only reliably mapped elements)
    *   **Confirmation Flag:** Evaluates and physically prints *`[PASS] No KEEP_RUNS ID appears in delete list.`* before handing back execution.

**Phase B: EXECUTE**
*   **Behavior:** Destructive sequestration.
*   **Execution:** Iterates over the verified `quarantine_targets`. Instead of `os.remove` (hard delete), the system utilizes `shutil.move()` transferring the artifacts to `TradeScan_State/quarantine/<TIMESTAMP>_cleanup/`.
*   **Outcome:** System is cleaned entirely, preserving absolute rollback capabilities mathematically bounded by the Timestamp.

---

## 6. Output Artifacts

1.  **Dry Run Report:** Grouped CLI output detailing counts and verification of invariants.
2.  **`cleanup_report.json`:** Emitted directly into `TradeScan_State/logs/` upon execution completion containing:
    *   `timestamp`: Execution time
    *   `runs_before`: Integer
    *   `runs_after`: Integer
    *   `deleted_counts`: Dictionary detailing directories (`runs`, `backtests`, `directives`)
    *   `retained_counts`: Dictionary detailing directories

---

## 7. Operational Constraints
*   **No Code Injection:** This workflow does not insert cleanup logic backward into core backtest evaluation loops.
*   **Strict Matching:** No regex or partial string matches `.contains()`. Direct strict equality `==` enforced exclusively across capitalization and structure (`abc1` != `ABC1`).
*   **No Versioning:** Quarantine is an isolated dump, no Git/Zlib artifact archiving wrapper is introduced.
*   **Minimalism:** Pure mathematical comparison + `shutil.move`.

---

## Addendum — 2026-03-24

### index.csv as Additional Lineage Source (Stage 1 Enhancement)

As of 2026-03-24, a central flat index exists at `TradeScan_State/research/index.csv`. This file is append-only and contains one row per completed Stage-1 run with `run_id`, `strategy_id`, `symbol`, `timeframe`, `profit_factor`, `max_drawdown_pct`, and `schema_version` among 15 fields.

**Impact on Stage 1 (Lineage Extraction):**
The `KEEP_RUNS` set can now be constructed — or cross-validated — directly from `index.csv` without parsing Excel spreadsheets:

```python
import csv
index_run_ids = {
    row["run_id"] for row in
    csv.DictReader(open(r"TradeScan_State\research\index.csv"))
    if row["run_id"]
}
```

This is faster and more reliable than spreadsheet parsing. The Excel sources (`Master_Portfolio_Sheet.xlsx`, `Filtered_Strategies_Passed.xlsx`) remain authoritative for portfolio membership; `index.csv` covers all Stage-1 runs regardless of portfolio inclusion.

**Recommended construction formula (updated):**
`KEEP_RUNS` = `[run_id FROM candidates]` ∪ `[split(constituent_run_ids) FROM strategies]` ∪ `[run_id FROM index.csv WHERE schema_version IN ('legacy','1.3.0')]`

**schema_version for cleanup decisions:**
`run_metadata.json` inside each `backtests/{strategy_id}_{symbol}/metadata/` folder now carries a `schema_version` field:
- `"legacy"` — pre-2026-03-24 runs (no content_hash, no git_commit)
- `"1.3.0"` — post-patch runs (full provenance: content_hash, git_commit, execution_model)

This field can be used to tier cleanup priority: legacy runs with no provenance and low PF are lower-risk candidates for quarantine than post-patch runs with full lineage.

### Backfill Note
`tools/backfill_run_index.py` populated the index with 167 legacy rows on 2026-03-24. Re-running it is safe — the duplicate guard (run_id match) prevents double-writes. `tools/run_index.py` handles all new runs automatically at `STAGE_1_COMPLETE`.
