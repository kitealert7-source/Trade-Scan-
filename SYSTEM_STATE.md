# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 4 uncommitted

> Generated: 2026-05-14T17:29:39Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 251 directives

## Ledgers

- **Master Filter:** 1133 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 130 rows — CORE: 4, FAIL: 120, PROFILE_UNRESOLVED: 1, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 511 rows — CORE: 14, FAIL: 342, LIVE: 13, RESERVE: 25, WATCH: 117

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-14** | Symbols: 235

## Artifacts
- Run directories: 1350

## Git Sync
- Remote: IN SYNC
- Working tree: 4 uncommitted
- Last substantive commit: `f5482f1 session: regenerate tools_manifest.json post-Phase-7a session`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch CLOSED_OK:** 5/5 runs clean (commit 1b6cc7b). Run `python tools/post_merge_watch.py --archive` to clear.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **Phase 7a Stage 3 — PASSED (2026-05-14).** Adversarial fail-closed battery — `TS_SignalValidator/tests/test_adversarial_phase7a.py`, commit `a4e3844`.
  - 18 tests, 3.28s runtime, 5 concern areas:
    - Hash determinism (5/5) — timestamp normalization, direction/symbol/precision sensitivity, idempotency
    - Atomic decision-write (5/5) — `os.replace` failure cleanup, prior-decision preservation, repeat-failure leak protection, cross-process seq monotonicity, monotonicity-with-gaps
    - Corpus integrity (3/3) — missing manifest, frozen=false, mutated content (against TEMP COPY — Section 1m-i preserved on real corpus)
    - Kill-switch stickiness (4/4) — `record_trade`/`validate_signal`/`verify_signal` after HALT all raise; `status_dict` reports HALTED
    - Process kill recovery (1/1) — spawn validator, `SIGKILL` mid-run, verify no `.tmp` leftovers, parseable `decision.json`, valid checksum, restart resumes seq
  - **Unblocks Stage 2** (1h accelerated stress) and **Stage 5** (72h Task Scheduler field stress) — those wall-clock costs are now safe to commit since the cheap fail-closed properties are pinned.

- **Phase 7a CODE-COMPLETE (2026-05-14).** Stages 1, 2, 3, 4 all PASSED; Stage 5 harness ready for operator-driven 72h run. Phase 7a is now ready to hand off to Phase 7b (TS_Execution shadow-read mode with `enable_validator_gating: false`) once Stage 5 completes.

- **Phase 7a Stage 4 — PASSED (2026-05-14, TSSV `39a331e`).** `pytest -m stage4 -v` → 5/5 in 15.64s. Closed the operator-flagged partial-coverage gap: Stage 1 = logic determinism, Stage 3 = atomic-write consistency, Stage 4 = full runtime determinism (two consecutive validator processes consuming same inputs produce byte-identical decision state). Triple-run convergence proven.

- **Phase 7a Stage 2 — 1h run PASSED substantively (2026-05-14, TSSV `39a331e`).** `validator_exit_code: 0`, 361 samples, 359 emissions over 3600s (exact 10s cadence). Handles 426 → 426 (ratio 1.0, **zero leak**). RSS 91,148,288 → 33,775,616 (ratio 0.3706, **RSS decreased** — Windows working-set trim of steady-state process; peak only +0.94 MB above baseline). Throughput 52,877 events/sec sustained (journal looped ~60× across the hour, ~190 million events processed total). Caveat: `process_clean_exit` flag false in summary — known false-positive from monitor process having loaded pre-fix `_summarize` code into memory before commit `b2e872a` landed; `validator_exit_code: 0` is authoritative.

- **Phase 7a Stage 2 — harness wired + 3 fixes landed (2026-05-14, TSSV commit `3a1a8ee`).** 60-second validation passed cleanly: 5 emissions in 55s (cadence matches `decision_emit_interval_s=10`), RSS 91,217,920 → 91,217,920 (ratio 1.0, zero growth), handles 426 → 426 (ratio 1.0, zero leak), validator exit 0. Projects to ~360 emissions, zero growth on both axes for a 1h run. Three operational bugs uncovered during validation:
  - **Fix 1 — WinError 5 retry-with-backoff** in `decision_emitter._atomic_replace_with_retry`. Windows Defender / file-explorer preview transiently locks `decision.json` post-close → `os.replace` ERROR_ACCESS_DENIED → validator FAIL-CLOSED after hundreds of successful writes. Now retries 5x with 10ms..160ms backoff on WinError 5/32 only. Non-retriable OSErrors (ENOSPC, etc.) still propagate on first attempt. New tests: `test_winerror_5_transient_then_succeeds`, `test_winerror_5_persistent_eventually_raises`.
  - **Fix 2 — cleanup orphan .tmp on emitter `__init__`**. SIGKILL between `tempfile.mkstemp` and `os.replace` leaves `.decision.*.tmp` debris. The atomic-rename contract is "decision.json never torn", NOT "no .tmp ever exists after crash". Post-crash debris is supervisor responsibility — `DecisionEmitter.__init__` (and `HeartbeatWriter.__init__`) now scrub leftovers via `dir.glob(".decision.*.tmp")`. Stage 3's `test_kill_mid_run_leaves_clean_state` updated to assert `decision.json` integrity post-kill AND `.tmp` absence post-RESTART (not pre-restart, which was racing the kill window). New test: `test_cleanup_on_init_removes_orphan_tmp`.
  - **Fix 3 — state-change emit on decision SHAPE, not full snapshot**. `aggregator.snapshot()` returns per-symbol dicts with `reason` strings carrying running counts (`hard_fail=N`, `signals=N+1`, ...) — comparing full snapshot triggered emission on every event → 363 emissions/sec under loop-journal stress (1.3M disk writes/hour). Now compares only `(overall_verdict, (symbol, per_symbol_verdict)*)` tuples. Periodic refresh emit is TIME-BASED (`decision_emit_interval_s=10s` default) instead of event-count-based — caps disk writes at ~6/min regardless of event throughput. `decision_emit_every_n` is opt-in / off by default.
  - **Stage 3 still passes (28/28 tests, 3.96s)** with all three fixes applied.
  - **1h run command:** `python tools/stage2_monitor.py --config config.shadow_journal.example.yaml --duration-s 3600 --sample-every-s 10` (TSSV repo). Operator-driven when ready.

- **Phase 7a Stage 5 — pending operational supervisor.** Windows Task Scheduler XML + heartbeat-stale monitor (per your earlier spec) — no longer a code blocker; just needs the supervisor configuration.

- **Phase 7a Stage 1 — PASSED (2026-05-14).** Shadow journal port-regression test for `TS_SignalValidator/validators/guard.py`:
  - Frozen corpus: `VALIDATION_DATASET/shadow_journal_2026_04_to_05/` — 33 days of real production observations (2026-04-05 → 2026-05-08), 21,871 events (7,722 SIGNAL + 7,689 ENTRY + 6,460 EXIT), 7 symbols, 10 strategy variants. Recovered from NAS `//FARAWAYTOURISM/home/TS_Execution/outputs/` after the 2026-05-09 retirement deletion.
  - Reference impl: `execution_engine/strategy_guard.py` (proven over the 33-day burn-in window).
  - Ported impl: `TS_SignalValidator/validators/guard.py` (this session, commit `e16a268`).
  - Reference output: `outputs/shadow_journal_strategy_guard_reference.jsonl` (commit `e2020cd`).
  - Port output: `TS_SignalValidator/outputs/shadow_journal_port_output.jsonl` (commit `e16a268`).
  - Diff: empty (exit 0). SHA-256 of both files: `c1f5dd7d74d329a3c73ebd25d19015cc763e75c5bccddd9d9d2af1785f038975`. Determinism: running port twice produces byte-identical output.
  - **Next sessions:** Stage 2 (1h accelerated stress on H2 P00 basket vault), Stage 3 (adversarial battery — kill-9, disk-full, corpus-corrupt, clock-skew), Stage 4 (already implicitly passed by re-run determinism), Stage 5 (72h+ Task Scheduler field stress with deliberate power-cycle disruption). The validation *logic* is now proven byte-identical to the 33-day production reference; the remaining stages test the operational supervisor, not the classifier.
  - **Subordinate concern (not blocking):** the journal's stored `signal_hash` uses a DIFFERENT hash function than `strategy_guard._compute_signal_hash` (production hash via `TS_Execution/src/signal_journal.py` includes `strategy_id`, returns full SHA-256, encodes direction as string). The reference set captures strategy_guard's classifications TODAY, not the historical production hashes — so the divergence does not affect Stage 1. If a future requirement is "validator must reproduce historical journal hashes byte-for-byte," that's a separate port (upgrade `_compute_signal_hash` to match `signal_journal.signal_hash`). Documented in `tools/replay_shadow_journal_reference.py` module docstring.

- **Broader-pytest failures outside gate suite (3 pre-existing remaining):**
  - `tests/test_state_paths_worktree.py` ×2 — pre-existing from 2026-05-11.
  - `tests/test_basket_directive_phase5.py::test_directive_legs_match_h2_spec` — pre-existing; the test asserts legacy H2 spec (USDJPY-short) but the directive was corrected to USDJPY-long in commit `5528ff1` (Phase 5d.1.1). Test needs to be updated to reflect the corrected spec; the directive is right, the test is stale.
  - ~~`tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive`~~ — **closed 2026-05-14** during Stage 2 wait window. Added 4 missing primitives to `_ALLOWED_PRIMITIVES` (`momentum_cmo`, `consecutive_highs_lows_breakout`, `dmi_wilder_directional`, `session_clock_universal`). All 5 tests in `test_indicator_semantic_contracts.py` now pass.
  - ~~`tests/test_engine_abi_v1_5_9.py::test_import_is_idempotent`~~ — **implicitly closed 2026-05-14** by the adversarial-test `importlib.reload()` fix (commit `fa7f1f8`). When `_force_reload_abi` stopped creating new module identities, this idempotency test stopped failing in full-suite runs.
  Note: the 2 `test_registry_integrity` failures from earlier today's close were closed by commit `7388453` (22-stub metadata backfill).
- ~~Manual-section persistence caveat~~ — **closed by commit `670bf02`** (`tools/system_introspection.py` now preserves the Manual section across regen verbatim; tests pinned in `tests/test_system_state_manual_persist.py`). This entry's own survival across the next regen is the validation proof.

- ~~Path B (Phase 5b.2) pending — next session priority~~ — **closed by commit `6aef5a1`** (`arch(phase-5b.2): Path B — basket dispatch writes discoverable artifacts`). Basket dispatcher now writes to `TradeScan_State/backtests/<directive_id>_<basket_id>/raw/results_tradelevel.csv`, registers in `run_registry.json`, appends to the MPS Baskets sheet. Phase 5d.1 followed and produced the 10-window parity matrix matching the research baseline (commit `5528ff1`).

- ~~Adversarial-test sys.modules ordering bug (introduced 2026-05-13 by Phase 0a)~~ — **closed 2026-05-14** during Stage 2 wait window. `_force_reload_abi` now uses `importlib.reload(mod)` instead of `del sys.modules + import_module`. The reload re-executes the module body in place (firing the runtime manifest assertion as designed) while preserving module identity — downstream importers who hold cached references see consistent state. Verified: `pytest tests/test_engine_abi_adversarial.py tests/test_basket_phase5c_real_data.py` (the previously-failing combo) returns 15/15 in 21s.
