# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 23 commits not pushed to origin

> Generated: 2026-05-03T14:57:49Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8a | **Status:** LEGACY | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 237 directives

## Ledgers

- **Master Filter:** 1036 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 455 rows — BURN_IN: 13, CORE: 14, FAIL: 294, RBIN: 2, RESERVE: 25, WATCH: 107

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** STOPPED (market_halt) | Last run: 2026-05-01T22:00:26Z
- **Shadow trades:** 4 active | **Signals (7d):** 22 entry, 28 exit
- **Alerts:** silence_alerts=ON | watchdog=IDLE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-03** | Symbols: 243

## Artifacts
- Run directories: 1238

## Git Sync
- Remote: **23 commits ahead of origin**
- Working tree: clean
- Last commit: `2f55ddf research: archive Phase 2 RSIAVG path study + orphan completed directives`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
