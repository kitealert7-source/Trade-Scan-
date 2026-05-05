# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: Latest data bar unknown

> Generated: 2026-05-05T05:38:31Z
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
- **Process:** RUNNING | run_id=20260505T032727Z_55340 | bars=63
- **Shadow trades:** 0 active | **Signals (7d):** 54 entry, 20 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **unknown** | Symbols: 0

## Artifacts
- Run directories: 1254

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last commit: `720e481 governance(indicators): enforce SIGNAL_PRIMITIVE contract across legacy indicators`

## Known Issues
### Auto-detected (regenerated each run)
- **Burn-in ABORT:** `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P06` — DD 25.57% >= abort threshold 12.0%

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

**SESSION STATUS = BROKEN — operator note 2026-05-05:**
- Triggered by empty `data_root/freshness_index.json` (regenerated mid-session at 04:23Z by a parallel thread; produced 0 entries). Not caused by this session's work. The compute_session_status check fires "BROKEN: Latest data bar unknown" when entries={}. Investigate next session: was DATA_INGRESS run with no symbols, or did `build_freshness_index` short-circuit?

**Burn-in ABORT context (carries from 2026-05-04):**
- The auto-detected `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P06_AUDJPY` ABORT (DD 25.57% > 12% threshold) is a real strategy-quality signal but **not actionable now** — a live burn-in is running for parity validation against backtest, cannot pause or modify any strategy until parity check completes. Triage after parity-check window closes.

**TD-003 partially advanced 2026-05-05** (parallel thread):
- `governance(indicators): enforce SIGNAL_PRIMITIVE contract across legacy indicators` (commit 720e481) added contract metadata + tests for several legacy indicators. Some may still be pending — verify with `python -m pytest tests/test_indicator_semantic_contracts.py`.

**Open infra items (deferred to next session):**
- **Batch 3.5** — `test_provision_only_integration.py` still skipped. Significant advance work landed today (canonical id format, idea_registry+sweep_registry injection, snapshot/restore, strategy.py.approved baseline). Remaining blocker: post-04c05c9 `EXPERIMENT_DISCIPLINE` + `SCHEMA_SAMPLE_MISSING` gates require either a strategy.py with `_schema_sample()` + pre-PROVISION-matching signature, OR a refactor away from subprocess to direct BootstrapController + PreflightStage Python-level testing. Detailed plan in the test's skip docstring.
- **Pipeline-error follow-ups (parallel thread):** stale `pending_signals.json` (yesterday's run_id, save_pending_state not firing on EXIT events); 7 of 9 active strategies producing 0 events in the fresh burn-in despite being loaded; `HALT_EQUITY_DD` guard alert at 2026-05-04T07:01Z (clearance state unverified). All being handled in the parallel TS_Execution thread per operator direction.

**Pre-existing TDs from prior sessions (still on the docket)**
- **TD-002** — Engine integrity drift caveat (HIGH, waived for NEWSBRK Phase 2 / v1.5.8a fork).
- **TD-003** — Indicator semantic-contract debt (LOW, partial fix landed in 720e481; verify residual count next session).
