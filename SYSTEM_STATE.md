# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-07T12:49:08Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 221 directives

## Ledgers

- **Master Filter:** 1062 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 473 rows — BURN_IN: 13, CORE: 14, FAIL: 307, RBIN: 2, RESERVE: 25, WATCH: 112

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260507T081405Z_17396 | bars=143
- **Shadow trades:** 1 active | **Signals (7d):** 53 entry, 21 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-07** | Symbols: 243

## Artifacts
- Run directories: 1280

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last substantive commit: `2cb5485 incident(2026-05-07): MASTER_DATA wipe recovery + junction-safety hardening`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch:** 1/5 observed; status=ACTIVE; commit=1b6cc7b.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **Pre-existing test failures (not gate-suite, auto-populator does not surface):** `pytest tests/` shows 10 failures concentrated in two files:
  - `tests/test_semantic_validator_engine_owned_fields.py` — 8 failures (semantic validator engine-owned field detection)
  - `tests/test_state_paths_worktree.py` — 2 failures (state path resolution under worktree env)
  These predate 2026-05-07 incident work and are non-blocking for the gate suite. Triage in a future session.

- **DATA RECOVERY incident — RESOLVED 2026-05-08:** First scheduled run failed (svc-data-ingress had no filesystem access — Phase 2 migration was incomplete; smoke test was a false positive). Resolved via Option Alpha: AntiGravity_Daily_Preflight reverted to `faraw + LogonType=S4U` (BATCH group bypasses INTERACTIVE deny). Validated 2026-05-08 06:29 IST: pipeline ran end-to-end, 1959 datasets validated, governance JSON SUCCESS. svc-data-ingress account **disabled**, TradeScan NAS Backup **re-enabled**. **Do not modify task principals or ACLs without re-reading [DATA_RECOVERY_REPORT.md](outputs/system_reports/09_incident_reports/DATA_RECOVERY_REPORT.md) §9** — the smoke-test false-positive trap is documented there.
