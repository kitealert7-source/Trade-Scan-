# SOP_CLEANUP.md (v3.0)

## 1. Purpose

This SOP defines how strategy-related artifacts are **retained, overwritten, and cleaned up** under a **Registry-Primary, Ledger-Protected** authority model.

- The **System Registry** (`run_registry.json`) is the primary ledger for run lifecycle state.
- Append-only Excel ledgers (`Filtered_Strategies_Passed.xlsx`, `Strategy_Master_Filter.xlsx`) act as a **fail-closed protection layer** over cleanup. They do not *authorize* deletion — they *prevent* it for canonical runs.
- The filesystem is the source of truth for physical run location; `resolve_run_dir` is the mandatory lookup helper.
- `Master_Portfolio_Sheet.xlsx` and UI reports are derived observations.

---

## 2. Authority Hierarchy

| Layer | Role | Artifact |
|---|---|---|
| **Primary — Run Lifecycle** | Registry decides what's retained | `TradeScan_State/registry/run_registry.json` |
| **Primary — Run Location** | Filesystem is canonical. Readers MUST use `resolve_run_dir(run_id)` | `RUN_DIRS_IN_LOOKUP_ORDER` in `config/state_paths.py` |
| **Protection — Defense in Depth** | Veto over deletion for canonical runs | `Filtered_Strategies_Passed.xlsx` (FSP), `Strategy_Master_Filter.xlsx` (SMF) |
| **Derived — Computation** | Non-authoritative summaries | `Master_Portfolio_Sheet.xlsx`, `AK_Trade_Report.xlsx` |
| **Disposable — UI** | Safely regenerable | `TradeScan_State/backtests/` |

**Note on the protection layer.** An earlier revision (v2.x) stated "Excel artifacts must never be used as authority for cleanup." That rule was narrowly correct (Excel does not *drive* deletion) but was read as "Excel has no veto," which caused the 2026-04-21 incident where canonical `is_current=1` runs were flagged for deletion. The current contract: registry authorizes cleanup; ledger vetoes it. Both layers must agree for a run to be removed.

---

## 3. Folder Role Definitions (Run Lifecycle)

Runs physically migrate through three directories in lifecycle order:

| Directory | Logical Tier | Role | Lifecycle Event That Places a Run Here |
|---|---|---|---|
| `TradeScan_State/runs/<run_id>/` | **sandbox (fresh)** | Stage-1 output container | Initial pipeline execution (run_stage1.py) |
| `TradeScan_State/sandbox/<run_id>/` (alias: `POOL_DIR`) | **sandbox (post-filter)** | Runs that have cleared the Master Filter | `filter_strategies.py` migrates runs here after Stage-3 |
| `TradeScan_State/candidates/<run_id>/` (alias: `SELECTED_DIR`) | **candidate** | Portfolio-consideration staging | Candidate promotion logic |

Additional directives-and-views folders:

| Directory | Role |
|---|---|
| `TradeScan_State/runs/<DIRECTIVE_ID>/` | Directive orchestration state. Contains `run_registry.json` (planned vs complete symbol runs). Cleared by `reset_directive.py` on full reset; preserved on `--to-stage4`. |
| `TradeScan_State/strategies/<ID>/` | Strategy home: `strategy.py`, `deployable/`, `portfolio_evaluation/`. Governed separately (see Snapshot Immutability in AGENT.md). |
| `TradeScan_State/backtests/<name>/` | Disposable UI views. Safely deletable if not tied to a registered run. |

### Canonical Lookup Rule

**Every reader that needs to locate an existing run MUST call `resolve_run_dir(run_id, require_data=...)`** from `config.state_paths`. Hardcoding `RUNS_DIR / run_id` is forbidden because it silently breaks once the run migrates to `POOL_DIR` (see 2026-04-21 `portfolio_evaluator` incident on run `56fdb79f…`).

---

## 4. Cleanup Invariants

### 4.1 What Is a Valid Run

A run is valid if it is indexed in the System Registry. Its `tier` and `status` fields determine cleanup eligibility. Its physical location is determined by `resolve_run_dir` at the time of action, not by a cached field.

### 4.2 Deletion Gate (ALL conditions must hold)

A run is eligible for physical deletion **only if** all the following are true:

1. `tier == "sandbox"` in the registry.
2. `status in {"complete", "aborted", "failed"}`.
3. `run_id` is **not** a member of any active portfolio.
4. `run_id` is **not** in the **Protected Canonical Set** (see 4.3).
5. If `status in {"aborted", "failed"}`: the run's `last_transition` timestamp in `run_state.json` is **older than 1 hour** (the **forensic cooldown gate**). Fresh failures require investigation; they must not be deleted out from under a running watchdog.

Runs that fail any check are logged and skipped — never deleted.

### 4.3 Protected Canonical Set (Fail-Closed Ledger Guard)

Before any deletion decision, `cleanup_reconciler` loads both ledgers and compiles a protection set:

| Ledger | Signal | Why |
|---|---|---|
| `Filtered_Strategies_Passed.xlsx` (FSP) | `is_current == 1` | Canonical flag — this is the live variant of its lineage |
| `Filtered_Strategies_Passed.xlsx` (FSP) | `candidate_status in {CORE, LIVE, WATCH, RESERVE, PROFILE_UNRESOLVED}` | Non-terminal lifecycle state — pending promotion or under review |
| `Strategy_Master_Filter.xlsx` (SMF) | Same two checks as above | Defense in depth against FSP write-lag during promotion windows |

**Fail-closed invariant.** If either ledger cannot be loaded (missing file, corrupt XLSX, unreadable columns), the reconciler **refuses to proceed** and raises `RuntimeError`. Silent unguarded cleanup would orphan ledger pointers and repeat the 2026-04-21 incident where five canonical runs were flagged for deletion.

### 4.4 Zombie Handling

A folder physically present but missing from the registry is **not** deleted on sight. It is **recovered** by `reconcile_registry` and injected as a sandbox-tier entry (with `directive_hash` restored from `run_state.json` when possible). Only after this recovery, and only if it passes every deletion gate above, may it be removed.

### 4.5 Snapshot Immutability

`TradeScan_State/runs/<RUN_ID>/strategy.py` is write-once after creation. Cleanup is permitted to delete the *entire run folder*; it may not edit, rename, or partially-prune artifacts within a surviving run folder.

---

## 5. Maintenance & Reconciliation Procedure

### 5.1 Reconciliation (always runs first)

`cleanup_reconciler.main()` invokes `reconcile_registry()` before any planning. This:

- Scans every directory in `RUN_DIRS_IN_LOOKUP_ORDER` (runs → sandbox → candidates).
- Injects orphan physical folders as sandbox-tier registry entries.
- Marks registered-but-missing runs as `invalid`.

### 5.2 Cleanup Workflow

1. **Dry Run:** `python tools/cleanup_reconciler.py`
   - Reports `[GUARD] N canonical run(s) protected from cleanup`.
   - Lists `[PLAN] ...` entries with the **resolved physical path** (not a hardcoded `runs/<rid>/` string).
   - Lists `[PROTECTED]` entries that the guard saved.
2. **Review:** Confirm no unexpected entries in the plan. Protected count should match rough expectation from FSP + SMF ledger size.
3. **Execute:** `python tools/cleanup_reconciler.py --execute`
   - Deletion target is `resolve_run_dir(r_id, require_data=False)` — the actual current location, not a guess. This is the fix for the v2.x silent no-op where registry rows were purged but migrated folders stayed on disk.
   - If the folder is already gone from disk, the registry row is still cleaned (logged as `[REGISTRY-ONLY]`).
   - UI view folders are deleted only after the `is_path_safe` physical guardrail passes.

### 5.3 Safety Rails in `is_path_safe`

Every deletion is double-checked:

- Path must not contain any forbidden segment: `strategies`, `candidates` (in Trade_Scan scope — not TradeScan_State SELECTED_DIR contents), `registry`, `tools`, `data_access`.
- Path must be a child of an allowed scope: any directory in `RUN_DIRS_IN_LOOKUP_ORDER`, or `BACKTESTS_DIR`.
- Any boundary violation raises `RuntimeError` — cleanup halts immediately.

---

## 6. Prohibitions

- **Inviolable artifacts.** `cleanup_reconciler` MUST NEVER delete:
  - `TradeScan_State/registry/run_registry.json`
  - Any run folder passing the Protected Canonical Set check
  - Any `TradeScan_State/strategies/<ID>/` folder (governed separately)
- **No hardcoded run paths.** Readers must go through `resolve_run_dir`. Writers targeting fresh Stage-1 output may still reference `RUNS_DIR` directly.
- **No Excel authority for authorization.** Deletion decisions originate from the registry; ledger reads grant *veto* only, never affirmative authority.
- **No manual `shutil.rmtree`.** All run-folder removals must go through `cleanup_reconciler` so the registry stays synchronized.
- **No deletion during active execution without explicit human sign-off.** Execution-active state defers structural cleanup (see preflight note).
- **No retention of `invalid` runs.** Runs flagged `invalid` during reconciliation are purged on the next maintenance cycle — after passing all gates in §4.

---

## 7. Guarantees

When enforced, this contract ensures:

- **Canonical runs are never silently lost.** Two independent ledgers (FSP + SMF) must both fail to protect a run before cleanup can remove it.
- **Registry-disk synchronization.** Every cleanup run reconciles first, so drift is healed before it can drive a deletion.
- **Migrated runs are cleanable.** The deletion path uses `resolve_run_dir`, so sandbox-tier runs that have moved to `POOL_DIR` are physically removed, not silently left on disk while the registry row is purged (v2.x bug, fixed 2026-04-21).
- **Fresh failures are preserved for forensics.** The 1-hour cooldown gate keeps aborted/failed runs intact long enough for a human to investigate.
- **Audit trail.** Every deletion decision is logged with the resolved path; every protection skip is logged with the run_id.

---

## 8. Version History

- **v3.0 (2026-04-21)** — Incorporated Protected Canonical Set (FSP + SMF fail-closed guard), cooldown gate for aborted/failed runs, `resolve_run_dir` as mandatory lookup helper, corrected folder-role table (sandbox/ is post-filter authoritative, not aggregation workspace), clarified that ledger reads grant veto not authority. Addresses 2026-04-21 canonical-run-flagging incident and silent-no-op deletion bug.
- **v2.1 (2026-03-19)** — Registry-first authority; Excel independence (narrowly interpreted).
- **v2.0 and earlier** — superseded.
