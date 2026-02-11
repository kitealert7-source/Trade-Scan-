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

## 8. Prohibitions

- No master-sheet reads to admit runs
- No timestamp-based cleanup
- No retention of partial or failed runs
- No manual artifact deletion

---

## 9. Guarantees

When enforced, this SOP ensures:
- bounded storage growth
- safe overwrite semantics
- deterministic cleanup
- audit-safe registry state

**Filesystem governs run start.  
Master sheet governs completed state.**
