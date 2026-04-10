# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 1 symbol(s) stale (>3 days behind)
- WARNING: Working tree 5 uncommitted

> Generated: 2026-04-10T15:06:56Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.4 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- **INBOX (3):** 40_CONT_UK100_15M_RSIPULL_SESSFILT_S09_V2_P00.txt, 40_CONT_UK100_15M_RSIPULL_SESSFILT_S10_V2_P00.txt, 40_CONT_UK100_15M_RSIPULL_SESSFILT_S11_V2_P00.txt
- Completed: 63 directives

## Ledgers

- **Master Filter:** 392 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 81 rows — CORE: 7, FAIL: 63, WATCH: 11
  - **Single-Asset Composites:** 42 rows — CORE: 4, FAIL: 29, WATCH: 9

- **Candidates (FPS):** 294 rows — BURN_IN: 8, CORE: 12, FAIL: 213, RBIN: 11, WATCH: 50

## Portfolio (TS_Execution)
- **Total entries:** 19 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 11

## Vault (DRY_RUN_VAULT)
- Snapshots: 10 | WAITING: 0 | Latest: `DRY_RUN_2026_04_09__b0527749`

## Data Freshness
- Latest bar: **2026-04-10** | Symbols: 250 | **Stale (>3d): 1**

## Artifacts
- Run directories: 527

## Git Sync
- Remote: IN SYNC
- Working tree: 5 uncommitted
- Last commit: `2c4d61a Add SESSION STATUS line to SYSTEM_STATE.md (OK/WARNING/BROKEN)`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
