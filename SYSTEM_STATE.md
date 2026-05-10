# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 7 uncommitted

> Generated: 2026-05-10T03:34:43Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 228 directives

## Ledgers

- **Master Filter:** 1068 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 479 rows — BURN_IN: 13, CORE: 14, FAIL: 313, RBIN: 2, RESERVE: 25, WATCH: 112

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 0 | WAITING: 0 | LIVE: 9 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260509T092018Z_23948 | bars=0
- **Shadow trades:** 0 active | **Signals (7d):** 50 entry, 27 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-10** | Symbols: 243

## Artifacts
- Run directories: 1286

## Git Sync
- Remote: IN SYNC
- Working tree: 7 uncommitted
- Last substantive commit: `88b4f28 session: closing SYSTEM_STATE snapshot`

## Known Issues
### Auto-detected (regenerated each run)
- **Gate suite: error running pytest** — could not parse pytest output
- Burn-in evaluator: error — No module named 'shadow_trades_reader'
- **Post-merge watch:** 1/5 observed; status=ACTIVE; commit=1b6cc7b.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
