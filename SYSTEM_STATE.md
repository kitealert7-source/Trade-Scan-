# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 8 symbol(s) stale (>3 days behind)
- WARNING: Working tree 3 uncommitted

> Generated: 2026-05-11T11:49:16Z
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
- Latest bar: **2026-05-11** | Symbols: 243 | **Stale (>3d): 8**

## Artifacts
- Run directories: 1289

## Git Sync
- Remote: IN SYNC
- Working tree: 3 uncommitted
- Last substantive commit: `d15a9b1 session: PSBRK rerun artifacts + SYSTEM_STATE close`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch CLOSED_OK:** 5/5 runs clean (commit 1b6cc7b). Run `python tools/post_merge_watch.py --archive` to clear.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
