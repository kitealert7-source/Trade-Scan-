# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 73 symbol(s) stale (>3 days behind)
- WARNING: Working tree 28 uncommitted

> Generated: 2026-04-21T10:02:45Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** LEGACY | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 136 directives

## Ledgers

- **Master Filter:** ERROR — No module named 'tools'

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`

- **Candidates (FPS):** 385 rows — BURN_IN: 8, CORE: 11, FAIL: 273, RBIN: 2, RESERVE: 17, WATCH: 74

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260421T074036Z_32076 | bars=43
- **Shadow trades:** 0 active | **Signals (7d):** 9 entry, 3 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 16 | WAITING: 0 | Latest: `DRY_RUN_2026_04_12__a2571097`

## Data Freshness
- Latest bar: **2026-04-21** | Symbols: 242 | **Stale (>3d): 73**

## Artifacts
- Run directories: 1114

## Git Sync
- Remote: IN SYNC
- Working tree: 28 uncommitted
- Last commit: `6f012ac skills(session-close): move SYSTEM_STATE regen to final step`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
