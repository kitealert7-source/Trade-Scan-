# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 8 symbol(s) stale (>3 days behind)
- WARNING: Working tree 3 uncommitted

> Generated: 2026-04-12T17:51:14Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.4 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 68 directives

## Ledgers

- **Master Filter:** ERROR — No module named 'tools'

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`

- **Candidates (FPS):** 303 rows — BURN_IN: 8, CORE: 11, FAIL: 221, RBIN: 11, RESERVE: 12, WATCH: 40

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** STOPPED (market_halt) | Last run: 2026-04-10T22:31:08Z
- **Shadow trades:** 1 active | **Signals (7d):** 11 entry, 9 exit
- **Alerts:** silence_alerts=ON | watchdog=IDLE

## Vault (DRY_RUN_VAULT)
- Snapshots: 16 | WAITING: 0 | Latest: `DRY_RUN_2026_04_12__a2571097`

## Data Freshness
- Latest bar: **2026-04-12** | Symbols: 250 | **Stale (>3d): 8**

## Artifacts
- Run directories: 533

## Git Sync
- Remote: IN SYNC
- Working tree: 3 uncommitted
- Last commit: `91f9d86 Enforce DB integrity: ON CONFLICT upserts, no Excel fallback, run_id identity`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
