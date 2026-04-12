# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 8 symbol(s) stale (>3 days behind)
- WARNING: Working tree 3 uncommitted

> Generated: 2026-04-12T10:09:23Z
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

- **Candidates (FPS):** 298 rows — BURN_IN: 8, CORE: 12, FAIL: 216, RBIN: 11, WATCH: 51

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 7 | WAITING: 0 | LIVE: 0 | LEGACY: 1

## Burn-In Status
- **Process:** STOPPED (market_halt) | Last run: 2026-04-10T22:31:08Z
- **Shadow trades:** 1 active | **Signals (7d):** 11 entry, 9 exit
- **Alerts:** silence_alerts=ON | watchdog=IDLE

## Vault (DRY_RUN_VAULT)
- Snapshots: 10 | WAITING: 0 | Latest: `DRY_RUN_2026_04_09__b0527749`

## Data Freshness
- Latest bar: **2026-04-12** | Symbols: 250 | **Stale (>3d): 8**

## Artifacts
- Run directories: 535

## Git Sync
- Remote: IN SYNC
- Working tree: 3 uncommitted
- Last commit: `ed45f20 Update manifests and add P06 directive from pipeline validation run`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
