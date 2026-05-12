# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 2 uncommitted

> Generated: 2026-05-12T12:47:43Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 232 directives

## Ledgers

- **Master Filter:** 1079 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 483 rows — CORE: 14, FAIL: 318, LIVE: 13, RESERVE: 25, WATCH: 113

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-11** | Symbols: 1

## Artifacts
- Run directories: 1289

## Git Sync
- Remote: IN SYNC
- Working tree: 2 uncommitted
- Last substantive commit: `7388453 infra: backfill 22 indicator-registry stubs to structural completeness`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch CLOSED_OK:** 5/5 runs clean (commit 1b6cc7b). Run `python tools/post_merge_watch.py --archive` to clear.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **Broader-pytest failures outside gate suite (3 pre-existing):**
  - `tests/test_state_paths_worktree.py` ×2 — pre-existing from 2026-05-11.
  - `tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive` — pre-existing; 4 new indicator primitives missing from the Classifier Gate `_ALLOWED_PRIMITIVES` allowlist. Separate concern from the Stage-0.5 allowlist landed today.
  Note: the 2 `test_registry_integrity` failures from earlier today's close were closed by commit `7388453` (22-stub metadata backfill).
- **Manual-section persistence caveat:** `tools/system_introspection.py` currently regenerates the entire SYSTEM_STATE.md file including the Manual section, despite the SKILL doc claiming "entries here persist". Operator must re-add Manual entries each session-close until the introspection script is fixed to merge rather than overwrite.
