# SOP_CLEANUP.md (v2)

## 1. Purpose

This SOP defines how strategy-related artifacts are **retained, overwritten, and cleaned up**
using a **two-phase authority model**.

- The filesystem governs **run start and overwrite behavior**.
- The Strategy Master Sheet governs **post-run retention, cleanup, and registry state**.

The master sheet acts only as a **repository and index** of completed runs.

---

## 2. Authority Model (Temporal)

### 2.1 Filesystem Authority (Pre-Commit)

At run start, the filesystem is the **only authoritative state**.

- Presence of `backtests/<strategy>/` determines overwrite behavior.

### 2.2 Master Sheet Authority (Post-Commit)

- **File:** `backtests/Strategy_Master_Filter.xlsx`
- **Primary Key:** `run_id` (globally unique, immutable)

The master sheet is written **only after successful run completion** and is authoritative for:
- retention
- cleanup
- registry state of completed runs
- MAY contain multiple rows per strategy, one per completed run.

---

## 3. Cleanup Invariants (Ledger Authority)

**Authoritative Ledger**
- `Strategy_Master_Filter.xlsx` is the sole authority for historical run retention.

**Valid Snapshot Definition**
- A `runs/<run_id>/` snapshot is valid if and only if it is indexed in the Master Sheet.

**Zombie Definition**
- A snapshot is classified as a zombie only if:
    1. It exists in `runs/<run_id>/`
    2. AND it does not have a corresponding Master Sheet entry.

**Materialized View Independence**
- The presence or absence of a `backtests/<strategy_symbol>/` folder does not determine snapshot validity.

---

## 4. Artifact Mapping

| Artifact | Path | Authority |
|--------|------|-----------|
| Strategy State (Latest) | `backtests/<strategy>/` | Derived |
| Strategy Code Snapshot | `runs/<run_id>/` | Authoritative |
| Run Identity | `backtests/<strategy>/metadata/run_metadata.json` | Authoritative |
| Batch Logs | `backtests/batch_summary_*.csv` | Non-authoritative |
| Master Index | `backtests/Strategy_Master_Filter.xlsx` | Authoritative (post-commit) |

---

## 5. Post-Run Commit Rules

After successful execution:

1. Generate new `run_id`.
2. Write:
   - `backtests/<strategy>/`
   - `runs/<run_id>/`

3. Upsert the corresponding row in the Strategy Master Sheet.

If the master sheet update fails:
- All newly created artifacts MUST be deleted or quarantined.
- No unindexed artifacts may persist.

---

## 6. Cleanup Procedure (Deterministic)

**Trigger:** Removal of a row from the Strategy Master Sheet.

**Execution Order:**
1. `rm -rf runs/<run_id>/`
2. `rm -rf backtests/<strategy>/`
3. Persist master sheet update

**Always Preserve:**
- `Strategy_Master_Filter.xlsx`
- `batch_summary_*.csv`
- directive/source files

Agents MUST derive cleanup targets exclusively by comparing filesystem state
against the current contents of Strategy_Master_Filter.xlsx at execution time.

Cleanup must not abort on partial deletion. Remaining artifacts are removed on the next sweep.

---

## 7. Integrity Enforcement

Periodic or startup integrity sweep must detect and resolve:

- Indexed rows with missing folders → remove row
- `runs/<run_id>/` folders not indexed → delete
- `backtests/<strategy>/` folders not indexed → delete
- `run_id` mismatch between metadata and sheet → invalidate row and delete artifacts

The filesystem is trusted for **existence**, the master sheet for **commit validity**.

---


## 8. Portfolio Evaluation Artifacts (Non-Strategy Layer)

### 8.1 Scope

Portfolio artifacts are analytical outputs derived from completed strategy runs.  
They do not affect strategy retention, overwrite behavior, or registry state.

Portfolio artifacts are independent of `Strategy_Master_Filter.xlsx`.

---

### 8.2 Portfolio Snapshot Definition

A portfolio snapshot consists of:

    strategies/<portfolio_id>/

and must contain:

- portfolio_composition.json
- portfolio-level evaluation artifacts (metrics, charts, reports)

---

### 8.3 Authority Model
    
- Portfolio existence is governed by `strategies/Master_Portfolio_Sheet.xlsx` (Authoritative).
- Portfolio folders MUST correspond to a valid row in the Master Portfolio Sheet.
- Deletion of strategy runs does NOT automatically delete portfolio folders (they are independent layers), BUT:
- Portfolio folders ARE subject to integrity reconciliation via `tools/cleanup_reconciler.py`.


---

### 8.4 Cleanup Rules

Portfolio folders:

- ARE subject to automatic cleanup sweeps by `tools/cleanup_reconciler.py`.
- Any portfolio folder not indexed in `Master_Portfolio_Sheet.xlsx` is a ZOMBIE and MUST be deleted.
- Any indexed row without a corresponding folder is an ORPHAN and MUST be removed from the sheet.
- Manual deletion is permitted, but automated reconciliation is preferred.


---

## 9. Prohibitions

### 9.1 Strategy Layer (Strict Governance)

The following actions are strictly forbidden for strategy artifacts governed by `Strategy_Master_Filter.xlsx`:

- No manual deletion of:
    - `runs/<run_id>/`
    - `backtests/<strategy>/`
- No timestamp-based cleanup logic
- No retention of partial or failed runs
- No artifact persistence without successful master sheet indexing
- No modification of indexed run artifacts outside authorized cleanup

Strategy artifacts are governed exclusively by the Strategy Master Sheet post-commit.

---

### 9.2 Portfolio Layer (Advisory Artifacts)

Portfolio artifacts are analytical and non-authoritative.

Therefore:

- Manual deletion of `strategies/<portfolio_id>/` is permitted. Automated cleanup via `tools/cleanup_reconciler.py` is the standard enforcement mechanism.

  If a portfolio folder is manually deleted, the corresponding row in
  `strategies/Master_Portfolio_Sheet.xlsx` MUST also be removed to
  maintain registry consistency.

`strategies/Master_Portfolio_Sheet.xlsx` is authoritative for portfolio existence.

- Portfolio folders ARE subject to integrity reconciliation against strategies/Master_Portfolio_Sheet.xlsx.
- Any portfolio folder without a corresponding Master_Portfolio_Sheet.xlsx entry MUST be deleted automatically during cleanup.
- Any Master_Portfolio_Sheet.xlsx row without a corresponding folder MUST be removed.
- Portfolio existence remains independent from strategy retention.
- Portfolio artifacts must not mutate underlying strategy artifacts.

---

## 10. Guarantees

When enforced, this SOP ensures:

### Strategy Layer:
- bounded storage growth
- safe overwrite semantics
- deterministic cleanup
- audit-safe registry state
- single-source-of-truth retention

### Portfolio Layer:
- analytical flexibility
- no cross-layer coupling
- preservation of strategy integrity
- clear separation between governance and analysis
- **auditable existence** via Master Portfolio Sheet

Filesystem governs run start.
Strategy Master Sheet governs completed strategy state.
Master Portfolio Sheet governs portfolio existence.


