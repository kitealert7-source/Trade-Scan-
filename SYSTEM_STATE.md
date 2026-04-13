# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 8 symbol(s) stale (>3 days behind)
- WARNING: Working tree 2 uncommitted

> Generated: 2026-04-13T16:00:28Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.4 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 106 directives

## Ledgers

- **Master Filter:** ERROR — No module named 'tools'

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`

- **Candidates (FPS):** 311 rows — BURN_IN: 8, CORE: 12, FAIL: 222, RBIN: 11, RESERVE: 10, WATCH: 48

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260413T000535Z_30728 | bars=359
- **Shadow trades:** 0 active | **Signals (7d):** 5 entry, 4 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 16 | WAITING: 0 | Latest: `DRY_RUN_2026_04_12__a2571097`

## Data Freshness
- Latest bar: **2026-04-13** | Symbols: 250 | **Stale (>3d): 8**

## Artifacts
- Run directories: 601

## Git Sync
- Remote: IN SYNC
- Working tree: 2 uncommitted
- Last commit: `f94900a Untrack data_root runtime files and add to .gitignore`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
