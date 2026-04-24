# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 6 uncommitted

> Generated: 2026-04-24T11:52:03Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** LEGACY | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 170 directives

## Ledgers

- **Master Filter:** 958 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 107 rows — CORE: 4, FAIL: 100, WATCH: 3
  - **Single-Asset Composites:** 68 rows — CORE: 11, FAIL: 52, WATCH: 5

- **Candidates (FPS):** 430 rows — BURN_IN: 12, CORE: 14, FAIL: 288, RBIN: 2, RESERVE: 25, WATCH: 89

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260423T072517Z_23648 | bars=528
- **Shadow trades:** 1 active | **Signals (7d):** 5 entry, 4 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 16 | WAITING: 0 | Latest: `DRY_RUN_2026_04_12__a2571097`

## Data Freshness
- Latest bar: **2026-04-24** | Symbols: 242

## Artifacts
- Run directories: 1159

## Git Sync
- Remote: IN SYNC
- Working tree: 6 uncommitted
- Last commit: `56c27c9 cleanup: remove orphan ZREV S05 directive inherited from prior session`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
