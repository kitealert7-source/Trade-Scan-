# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 26 symbol(s) stale (>3 days behind)
- WARNING: Working tree 8 uncommitted

> Generated: 2026-05-04T10:50:51Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** LEGACY | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 210 directives

## Ledgers

- **Master Filter:** 1043 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 457 rows — BURN_IN: 13, CORE: 14, FAIL: 294, RBIN: 2, RESERVE: 25, WATCH: 109

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260504T011609Z_29588 | bars=286
- **Shadow trades:** 2 active | **Signals (7d):** 43 entry, 40 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-04** | Symbols: 243 | **Stale (>3d): 26**

## Artifacts
- Run directories: 1247

## Git Sync
- Remote: IN SYNC
- Working tree: 8 uncommitted
- Last commit: `cec5d70 chore: append session pipeline audit entries`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
