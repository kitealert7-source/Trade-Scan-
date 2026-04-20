# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 1 commits not pushed to origin

> Generated: 2026-04-20T06:31:37Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.7 | **Status:** LEGACY | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 127 directives

## Ledgers

- **Master Filter:** 865 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 104 rows — CORE: 4, FAIL: 96, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 63 rows — CORE: 9, FAIL: 47, PROFILE_UNRESOLVED: 1, WATCH: 6

- **Candidates (FPS):** 407 rows — BURN_IN: 15, CORE: 12, FAIL: 270, RBIN: 11, RESERVE: 21, WATCH: 78

## Portfolio (TS_Execution)
- **Total entries:** 8 | **Enabled:** 8
- BURN_IN: 8 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260420T024639Z_28776 | bars=60
- **Shadow trades:** 0 active | **Signals (7d):** 16 entry, 5 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 16 | WAITING: 0 | Latest: `DRY_RUN_2026_04_12__a2571097`

## Data Freshness
- Latest bar: **2026-04-20** | Symbols: 242

## Artifacts
- Run directories: 1068

## Git Sync
- Remote: **1 commits ahead of origin**
- Working tree: 10 uncommitted
- Last commit: `d8d736c engine(v1.5.8): add ctx.unrealized_r_intrabar + ctx.entry_price; EXPERIMENTAL`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->
- (none)
