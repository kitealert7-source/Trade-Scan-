# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 4 uncommitted

> Generated: 2026-05-14T05:42:10Z
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
- Last substantive commit: `1834276 session: regenerate tools_manifest.json post-Phase-5b.4`

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

- **Phase 7a Stage 2 (NEXT) + 5 — ready when supervisor is configured.** Stage 2 requires no new code (just `python run_validator.py --config config.shadow_journal.example.yaml` with no `--max-iters`; consumes all 21,871 events). Stage 5 requires the Windows Task Scheduler XML + heartbeat-stale-monitor script per your earlier spec.

- **Phase 7a Stage 1 — PASSED (2026-05-14).** Shadow journal port-regression test for `TS_SignalValidator/validators/guard.py`:
  - Frozen corpus: `VALIDATION_DATASET/shadow_journal_2026_04_to_05/` — 33 days of real production observations (2026-04-05 → 2026-05-08), 21,871 events (7,722 SIGNAL + 7,689 ENTRY + 6,460 EXIT), 7 symbols, 10 strategy variants. Recovered from NAS `//FARAWAYTOURISM/home/TS_Execution/outputs/` after the 2026-05-09 retirement deletion.
  - Reference impl: `execution_engine/strategy_guard.py` (proven over the 33-day burn-in window).
  - Ported impl: `TS_SignalValidator/validators/guard.py` (this session, commit `e16a268`).
  - Reference output: `outputs/shadow_journal_strategy_guard_reference.jsonl` (commit `e2020cd`).
  - Port output: `TS_SignalValidator/outputs/shadow_journal_port_output.jsonl` (commit `e16a268`).
  - Diff: empty (exit 0). SHA-256 of both files: `c1f5dd7d74d329a3c73ebd25d19015cc763e75c5bccddd9d9d2af1785f038975`. Determinism: running port twice produces byte-identical output.
  - **Next sessions:** Stage 2 (1h accelerated stress on H2 P00 basket vault), Stage 3 (adversarial battery — kill-9, disk-full, corpus-corrupt, clock-skew), Stage 4 (already implicitly passed by re-run determinism), Stage 5 (72h+ Task Scheduler field stress with deliberate power-cycle disruption). The validation *logic* is now proven byte-identical to the 33-day production reference; the remaining stages test the operational supervisor, not the classifier.
  - **Subordinate concern (not blocking):** the journal's stored `signal_hash` uses a DIFFERENT hash function than `strategy_guard._compute_signal_hash` (production hash via `TS_Execution/src/signal_journal.py` includes `strategy_id`, returns full SHA-256, encodes direction as string). The reference set captures strategy_guard's classifications TODAY, not the historical production hashes — so the divergence does not affect Stage 1. If a future requirement is "validator must reproduce historical journal hashes byte-for-byte," that's a separate port (upgrade `_compute_signal_hash` to match `signal_journal.signal_hash`). Documented in `tools/replay_shadow_journal_reference.py` module docstring.

- **Broader-pytest failures outside gate suite (3 pre-existing):**
  - `tests/test_state_paths_worktree.py` ×2 — pre-existing from 2026-05-11.
  - `tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive` — pre-existing; 4 new indicator primitives missing from the Classifier Gate `_ALLOWED_PRIMITIVES` allowlist. Separate concern from the Stage-0.5 allowlist landed today.
  Note: the 2 `test_registry_integrity` failures from earlier today's close were closed by commit `7388453` (22-stub metadata backfill).
- ~~Manual-section persistence caveat~~ — **closed by commit `670bf02`** (`tools/system_introspection.py` now preserves the Manual section across regen verbatim; tests pinned in `tests/test_system_state_manual_persist.py`). This entry's own survival across the next regen is the validation proof.

- **Path B (Phase 5b.2) pending — next session priority:** basket pipeline dispatch currently writes to `DRY_RUN_VAULT/baskets/<dir_id>/<basket_id>/` + `TradeScan_State/research/basket_runs.csv`, NOT the standard `backtests/` layout. User pushed back end-of-session 2026-05-13: results must be discoverable later, not just produced — ad-hoc CSVs in basket_runs.csv lose visibility across sessions. Path B extends the dispatcher in `tools/run_pipeline.py` + `tools/portfolio_evaluator.py` to mirror the per-symbol artifact layout: `TradeScan_State/backtests/<directive_id>/raw/results_tradelevel.csv`, `run_registry.json` entry, MPS row with `execution_mode='basket'`. Touches Protected Infrastructure → needs implementation plan + approval before edit. Blocker for Phase 5d.1 (the 10-window basket_sim parity run; we want each window's result discoverable in `backtests/`). See `~/.claude/projects/.../memory/project_h2_engine_promotion_plan.md` for full state.

- **Adversarial-test sys.modules ordering bug (introduced 2026-05-13 by Phase 0a):**
  `tests/test_engine_abi_adversarial.py::_force_reload_abi` deletes every
  `engine_abi*` entry from `sys.modules` and re-imports. When subsequent
  test modules then import `engine_abi.v1_5_9`, the runtime manifest
  assertion in `__init__.py:79` fires because module identity differs
  from the cached reference. All 5 tests in `test_engine_abi_adversarial.py`
  and `test_basket_phase5c_real_data.py::test_dispatch_against_h2_directive_with_real_data`
  fail in full-suite pytest runs while passing individually. Pre-commit
  gate roster is unaffected (does not include these tests).
  Fix candidate: `_force_reload_abi` should `importlib.reload()` instead
  of bare `del + import_module`, OR add a session-scoped pytest fixture
  that re-imports `engine_abi.v1_5_9` after any adversarial test. Filed
  as Phase 0a follow-up; not blocking H2 promotion plan execution.
