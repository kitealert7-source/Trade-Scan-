# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-07T05:58:35Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 221 directives

## Ledgers

- **Master Filter:** 1061 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 472 rows — BURN_IN: 13, CORE: 14, FAIL: 307, RBIN: 2, RESERVE: 25, WATCH: 111

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260507T052553Z_15256 | bars=13
- **Shadow trades:** 1 active | **Signals (7d):** 53 entry, 21 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-07** | Symbols: 243

## Artifacts
- Run directories: 1281

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `856bea8 migration(raw_min_lot): observational burn-in + lot-rescaled metrics + RAW_MIN_LOT_V1 default`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch:** 0/5 observed; status=ACTIVE; commit=1b6cc7b.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
