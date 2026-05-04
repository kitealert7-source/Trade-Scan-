# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 26 symbol(s) stale (>3 days behind)

> Generated: 2026-05-04T16:34:37Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- **INBOX (1):** 64_REV_XAUUSD_1H_FVG_S01_V1_P00.txt
- Completed: 203 directives

## Ledgers

- **Master Filter:** 1043 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 457 rows — BURN_IN: 13, CORE: 14, FAIL: 294, RBIN: 2, RESERVE: 25, WATCH: 109

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260504T011609Z_29588 | bars=471
- **Shadow trades:** 3 active | **Signals (7d):** 41 entry, 43 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-04** | Symbols: 243 | **Stale (>3d): 26**

## Artifacts
- Run directories: 1247

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last commit: `b42b27b docs(session): align session-close gate + CLAUDE.md path rules with this session's infra changes`

## Known Issues
### Auto-detected (regenerated each run)
- **Burn-in ABORT:** `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P02` — Fill rate 71.4% < abort threshold 80.0%

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

**Burn-in ABORT context (operator note 2026-05-04):**
- The auto-detected `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P02` ABORT (Fill Rate 71.4%) is suspected to be a code-error artifact, not a strategy failure — no signals were firing during the burn-in window. Triage in next session.

**TD-007 — Migrate `tools/burnin_evaluator.py` local resolver to `config.path_authority`** (Risk: LOW)
- File has its own `_resolve_ts_exec_root()` walk-up helper from earlier this session that predates `path_authority`. ~5-line replacement; drops the lint exemption.
- **Action: cleanup follow-up, not blocking.**

**Quarantined tests (deferred to Batch 3 — test architecture modernization)**
- `test_step6_state_machine_invariants.py` — 4 tests skipped, need rewrite for BootstrapController + StageRunner architecture.
- `test_provision_only_integration.py::test_run_pipeline_provision_only` — 1 test skipped, blocked by namespace-gate canonical pattern on `TEST_PROVISION_<random>` ids.

**Pre-existing TDs from prior sessions (still on the docket)**
- **TD-002** — Engine integrity drift caveat (HIGH, waived for NEWSBRK Phase 2 / v1.5.8a fork).
- **TD-003** — Indicator semantic-contract debt (LOW, ~18 indicators missing `SIGNAL_PRIMITIVE` metadata; governance cleanup).
