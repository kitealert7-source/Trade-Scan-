# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 5 commits not pushed to origin

> Generated: 2026-04-19T16:12:08Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.6 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 187 directives

## Ledgers

- **Master Filter:** 735 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 104 rows — CORE: 4, FAIL: 96, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 63 rows — CORE: 9, FAIL: 47, PROFILE_UNRESOLVED: 1, WATCH: 6

- **Candidates (FPS):** 407 rows — BURN_IN: 15, CORE: 12, FAIL: 270, RBIN: 11, RESERVE: 21, WATCH: 78

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260418T181517Z_9320 | bars=22
- **Shadow trades:** 0 active | **Signals (7d):** 16 entry, 6 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 16 | WAITING: 0 | Latest: `DRY_RUN_2026_04_12__a2571097`

## Data Freshness
- Latest bar: **2026-04-19** | Symbols: 242 | **Stale (>3d): 18**

## Artifacts
- Run directories: 958

## Git Sync
- Remote: **5 commits ahead of origin**
- Working tree: 156 uncommitted
- Last commit: `1f5c094 Compact RESEARCH_MEMORY: advance archive threshold to 2026-04-14`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
