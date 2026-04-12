# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 8 symbol(s) stale (>3 days behind)
- WARNING: Working tree 8 uncommitted

> Generated: 2026-04-12T02:01:02Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.4 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 67 directives

## Ledgers

- **Master Filter:** 395 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 81 rows — CORE: 7, FAIL: 63, WATCH: 11
  - **Single-Asset Composites:** 42 rows — CORE: 4, FAIL: 29, WATCH: 9

- **Candidates (FPS):** 297 rows — BURN_IN: 8, CORE: 12, FAIL: 216, RBIN: 11, WATCH: 50

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
- Run directories: 530

## Git Sync
- Remote: IN SYNC
- Working tree: 8 uncommitted
- Last commit: `54989d4 Update SYSTEM_STATE.md â€” session close snapshot`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
