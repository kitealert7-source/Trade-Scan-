# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 1 commits not pushed to origin

> Generated: 2026-05-10T04:48:17Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 226 directives

## Ledgers

- **Master Filter:** 1068 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 479 rows — CORE: 14, FAIL: 314, LIVE: 13, RESERVE: 25, WATCH: 113

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-10** | Symbols: 243

## Artifacts
- Run directories: 1286

## Git Sync
- Remote: **1 commits ahead of origin**
- Working tree: 41 uncommitted
- Last substantive commit: `c1f6d83 infra: delete BURN_IN consumer scaffolding (post TS_Execution rebuild)`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch:** 1/5 observed; status=ACTIVE; commit=1b6cc7b.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
