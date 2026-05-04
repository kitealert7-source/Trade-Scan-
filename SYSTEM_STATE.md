# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 26 symbol(s) stale (>3 days behind) — non-XAU instruments only (ESP35, EUSTX50, FRA40, GER40); not in this session's scope
- WARNING: Working tree 7 uncommitted — UNTRACKED ARTIFACTS ONLY (FVG idea-64 completed-directive .txt files in backtest_directives/completed/; INBOX is empty; no tracked files modified)

> Generated: 2026-05-04T10:54:27Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** LEGACY | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 210 directives

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
- **Process:** RUNNING | run_id=20260504T011609Z_29588 | bars=286
- **Shadow trades:** 2 active | **Signals (7d):** 43 entry, 40 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-04** | Symbols: 243 | **Stale (>3d): 26**

## Artifacts
- Run directories: 1247

## Git Sync
- Remote: IN SYNC
- Working tree: 7 uncommitted
- Last commit: `7021811 session: closing SYSTEM_STATE snapshot`

## Known Issues
<!-- Update manually at session end: note anything broken, deferred, or pending -->

### Tech-debt items recorded this session

**TD-001 — In-place contract regressions** (Risk: **MED**)
- Tests: `tests/indicator/test_inplace_contract.py` (2 fails)
- Affected: `indicators/price/candle_state.py`, `indicators/price/previous_bar_breakout.py`
- Both indicators return a new DataFrame instead of mutating in place — wastes memory on the engine hot path; functional correctness unaffected.
- **Action: resolve before next research session** (real regression, not stale test).

**TD-002 — Engine integrity caveat (canonical-hash regen masks f3ae767 drift)** (Risk: **HIGH (waived)**)
- Tests: `tests/test_engine_integrity_canonical_hash.py::TestRealDriftStillDetected::test_f3ae767_drifted_files_still_fail` (3 sub-fails)
- Cause: This session regenerated `engine_dev/.../v1_5_8/engine_manifest.json` with current canonical hashes during the manifest-hashing unification (commit `fea0bb8`/`56eeb33`). Pre-regen, the manifest carried pre-drift raw-bytes hashes from the `b63e94f` freeze; integrity would have FAILED to expose the post-freeze `f3ae767` (check_exit v1.3 contract) drift. Post-regen the manifest matches current files, so the test's drift-detection premise no longer holds.
- **Action: resolve or formally waive when NEWSBRK Phase 2 / v1.5.8a fork work resumes on `main`.** Documented in commit `56eeb33` for forensic rollback.

**TD-003 — Indicator semantic-contract debt** (Risk: **LOW**)
- Tests: `tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive` (1 fail)
- Cause: ~18 indicators are missing `SIGNAL_PRIMITIVE` metadata or use a value not in the allowlist. Includes `fair_value_gap` (this session), plus `macd`, `roc`, `rsi_smoothed`, `candle_sign_sequence`, `consecutive_closes`, `previous_bar_breakout`, `rolling_zscore`, `adx`, `adx_wilder`, `hull_moving_average`, `hurst_regime`, `hurst_rs`, `ema_cross`, `gaussian_slope`, `atr_with_dollar_floor`, `atr_with_pip_floor`, `bar_range`.
- **Action: governance cleanup** — decide whether the contract is enforced (then expand allowlist + add metadata to each indicator) or relaxed (then retire/update the test).

### Quarantined tests (deferred to Batch 3 — test architecture modernization)
- `test_step6_state_machine_invariants.py` — 4 tests skipped: 3 in `TestRunPipelineScenarioInvariants` (architecture changed from direct sequential calls to BootstrapController + StageRunner; need rewrite to mock new boundaries) + 1 in `TestMultiSymbolPartialFailureInvariant` (fixture path: needs `runs/<rid>/data/` instead of `backtests/<sym>/raw/`).
- `test_provision_only_integration.py::test_run_pipeline_provision_only` — 1 test skipped after outer fixture fix (`active/` → `INBOX/`) exposed a second-layer staleness: directive id format is `TEST_PROVISION_<random>` which fails the namespace gate's canonical pattern `<ID>_<FAMILY>_<SYMBOL>_<TF>_<MODEL>[_<FILTER>]_S<NN>_V<N>_P<NN>`.

### Operational
**Burn-in alert (pre-existing, not caused by this session)**
- Strategy: `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P02`
- Verdict: **ABORT** — Fill Rate 71.4% (below threshold)
- Detected by: `python tools/burnin_evaluator.py` during this session-close; also visible to next session.
- **Action: triage in next session.** Strategy is from idea-22 RSIAVG family, predates this session's FVG work.
