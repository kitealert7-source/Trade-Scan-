# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: Latest data bar unknown

> Generated: 2026-05-17T14:43:35Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 478 directives

## Ledgers

- **Master Filter:** 1151 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 121, PROFILE_UNRESOLVED: 1, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 521 rows — CORE: 14, FAIL: 351, LIVE: 13, RESERVE: 25, WATCH: 118

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **unknown** | Symbols: 0

## Artifacts
- Run directories: 1576

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `ad6e962 session: registry backfill + pytest baseline update (3 new failures resolved)`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 1 acknowledged failure(s) (last refreshed 2026-05-17 @ 66f15bd2). Tests: test_basket_dispatch_emits_run_state_and. Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **`data_root/freshness_index.json` is currently EMPTY (0 entries) — root cause of SESSION STATUS=BROKEN.** Data itself is intact on disk (verified per-symbol path access works). The `engines/ops/build_freshness_index.py` script in DATA_INGRESS wrote an empty index when invoked from this session; per-symbol rebuild attempts also returned 0 entries (likely a `pd.read_csv(usecols=['time'])` failure mode under the ACL bypass pattern). Not actionable mid-close; flagging for next session to investigate the build_freshness_index script or use the daily scheduled task to regenerate. SYSTEM_STATE shows `Symbols: 0` until the index is rebuilt.
