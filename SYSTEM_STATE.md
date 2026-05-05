# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-05T16:51:31Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 218 directives

## Ledgers

- **Master Filter:** 1058 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 469 rows — BURN_IN: 13, CORE: 14, FAIL: 305, RBIN: 2, RESERVE: 25, WATCH: 110

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260505T032727Z_55340 | bars=420
- **Shadow trades:** 2 active | **Signals (7d):** 53 entry, 21 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-05** | Symbols: 243

## Artifacts
- Run directories: 1275

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last commit: `38aa3e9 session: closing SYSTEM_STATE snapshot â€” PSBRK V4 sweep`

## Known Issues
### Auto-detected (regenerated each run)
- **Burn-in ABORT:** `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P06` — DD 27.98% >= abort threshold 12.0%

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
