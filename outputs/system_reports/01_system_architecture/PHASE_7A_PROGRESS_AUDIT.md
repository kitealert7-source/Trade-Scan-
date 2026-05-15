# Phase 7a — Progress Audit

**Plan ref:** `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md`
v11 (LOCKED, 2026-05-13).

**Status as of 2026-05-14 (end of session):** **Phase 7a CODE-COMPLETE.**
Stages 1, 2, 3, 4 PASSED. Stage 5 supervisor harness ready for
operator-driven 72h field stress.

This document is the operator-facing audit trail. It captures *what
was done*, *what's pending*, *what evidence was produced*, and *what
the next operator needs to know* — not architectural rationale (that
lives in the plan).

---

## 1. Architectural reframings vs the v11 plan

The plan called for a single Stage 7a observation gate: "≥ 14 calendar
days of validator emitting decisions continuously on at least one
promoted vault, with determinism check." During execution, the
operator (kitealert) chose to **decompose that single gate** into a
5-stage acceptance battery — same defensibility, smaller wall-clock
cost, stronger per-property evidence:

| Stage | Tests | Wall-clock cost | Property |
|---|---|---|---|
| 1 | Shadow journal port-regression (byte-diff vs `strategy_guard.py`) | ~30s | Validation logic faithful to proven 33-day production reference |
| 2 | Accelerated stress + resource monitor | 1h | Resource stability — RSS growth, handle leak, file churn, throughput |
| 3 | Adversarial fail-closed battery | 3–4s | Atomic-write, corpus integrity, kill-switch stickiness, hash determinism, process kill |
| 4 | Explicit runtime determinism replay | ~15s (5 subprocess pairs/triples) | Same inputs → byte-identical decision state across runs |
| 5 | Field stress via Windows Task Scheduler | ≥ 72h elapsed | OS-level survival — kill recovery, hibernate, cold boot, hard reset, sleep |

Total elapsed of the battery: **~73h** vs plan's 14 days = ~336h.
~4.6× speedup with stronger per-property evidence + explicit
defensibility for each property.

The plan's 14-day wall-clock requirement was conservative for the case
where the validation logic was being *built from scratch*. The shadow
journal recovery (see §2) revealed that 80% of the logic was already
proven over 33 days in the prior burn-in regime, so the battery only
needed to test what was *new* (the port and the supervisor) rather
than re-validate what was *already proven*.

---

## 2. Shadow journal recovery — the key enabler

On 2026-05-14, the operator's NAS-side backup yielded the
**pre-retirement** TS_Execution shadow infrastructure:

- `outputs/shadow_trades.jsonl` (26 MB, 21,871 events, 33 days
  2026-04-05 → 2026-05-08)
- `src/shadow_logger.py` / `src/shadow_trades_reader.py` (deleted in
  TS_Execution commit `191c8da` on 2026-05-09)
- `tools/burnin_monitor.py` (25 KB, periodic burn-in metric
  assessor)
- Daily snapshots in `DRY_RUN_VAULT/shadow_backups/` (9 files)

These artifacts represent **30+ days of real production validation
observations** on the per-symbol portfolio (PINBAR, KALFLIP, RSIAVG ×
4 variants, IMPULSE). The validation thresholds (`loss_streak × 1.5`,
`WR × 0.65`, `DD × 2.0`, price tolerance 0.001, time window 60s) were
empirically calibrated against this real production distribution.

**Architectural decision:** these artifacts were respected as
deleted-code reference material. We *read* them to inform the port
but did *not* resurrect them into tracked paths — the retirement
commits (`191c8da`, `c1f6d83`, `f1b613a`, `f408332`) were intentional
and pushed. The new validator logic was written into `TS_SignalValidator/`
(per plan Section 1l: the new repo is the right home).

**Frozen corpus added:**
`VALIDATION_DATASET/shadow_journal_2026_04_to_05/` — sibling to the
existing `h2_validator_baseline_v1`. Manifest produced, verified,
files chmod'd read-only. Section 1m-i invariant preserved
(`h2_validator_baseline_v1` untouched).

---

## 3. Stage-by-stage execution record

### Stage 1 — Shadow journal port-regression (PASSED)

- **TS_SignalValidator** commit `e16a268` (2026-05-14)
- **Trade_Scan** commit `e2020cd` (2026-05-14)

Both `Trade_Scan/tools/replay_shadow_journal_reference.py` (runs the
proven `execution_engine/strategy_guard.py`) and
`TS_SignalValidator/tools/replay_journal_port.py` (runs the ported
`validators/guard.py`) classify all 7,722 SIGNAL events in the shadow
journal corpus. **Output byte-identical**, SHA-256
`c1f5dd7d74d329a3c73ebd25d19015cc763e75c5bccddd9d9d2af1785f038975`.

Coverage:
- 7 base strategies (PINBAR, KALFLIP, RSIAVG × 4 variants, IMPULSE)
- 7 symbols (NAS100, XAUUSD, GBPJPY, AUDJPY, BTCUSD, AUDUSD, EURUSD)
- 100% HARD_FAIL — the correct classification (every journal event is
  a live signal beyond the per-vault research backtest window)

Subordinate finding documented (not blocking): the journal's stored
`signal_hash` uses a different formula than
`strategy_guard._compute_signal_hash` (production includes
`strategy_id` in the inputs, returns full 64-char SHA-256, uses
direction as string). Audit trail in
`tools/replay_shadow_journal_reference.py` module docstring.

### Stage 3 — Adversarial fail-closed battery (PASSED)

- **TS_SignalValidator** commit `a4e3844` (original 18 tests)
- **TS_SignalValidator** commit `3a1a8ee` (3 additional tests after
  Stage 2 prep uncovered 3 real bugs)

**21 tests, runtime 3.96s.** Five concern areas:

1. Hash determinism (5/5) — timestamp normalization, direction
   sensitivity, symbol sensitivity, 5dp precision, normalization
   idempotency.
2. Atomic decision-write (8/8) — `os.replace` failure cleanup,
   prior-decision preservation, repeat-failure no-leak, cross-process
   seq monotonicity, seq strictly monotone even with intervening
   failures, WinError 5 transient-then-succeeds, WinError 5 persistent
   eventually-raises, cleanup-on-init removes orphan `.tmp`.
3. Corpus integrity (3/3) — missing manifest, `frozen: false`, mutated
   content (against TEMP COPY — Section 1m-i preserved on real
   corpus).
4. Kill-switch stickiness (4/4) — `record_trade` / `validate_signal` /
   `verify_signal` after halt all raise; `status_dict` reports HALTED.
5. Process kill recovery (1/1) — subprocess kill mid-run, verify
   `decision.json` integrity post-kill + valid checksum + `.tmp`
   cleanup post-RESTART (not pre-restart, which races the kill window).

### Stage 2 — Accelerated stress + resource monitor (PASSED — 1h run complete)

**Harness:** `TS_SignalValidator/tools/stage2_monitor.py`
**TS_SignalValidator** commit `3a1a8ee`.

The harness spawns the validator as a subprocess (with new
`--loop-journal` and `--max-duration-s` flags) and samples
**RSS, num_handles, decision seq_no delta, heartbeat extras** via
`psutil` every N seconds. JSONL metric stream + JSON summary with
pass-criteria flags.

**Three real bugs uncovered during 60s validation** (this is the value
of the fail-fast staging order — found in seconds, not hours):

| Bug | Surfaced by | Fix |
|---|---|---|
| `os.replace` ERROR_ACCESS_DENIED on Windows after hundreds of writes (antivirus / file-explorer transient lock) | First 60s run FAIL-CLOSED after ~300 successful writes | `_atomic_replace_with_retry`: 5 attempts, 10–160ms exponential backoff, on WinError 5/32 only. ENOSPC and other non-retriable errors still propagate on first attempt. |
| `.decision.*.tmp` debris after SIGKILL (atomic-rename contract is "no torn final file" — `.tmp` debris is normal post-crash) | Stage 3 kill-test started failing after the retry fix widened the write window | `_cleanup_orphan_tmp_files` runs on emitter `__init__` — supervisor pattern. Stage 3 kill test updated to assert post-RESTART cleanup, not pre-restart. |
| 363 emits/sec (1.3M writes/hour projected) because `aggregator.snapshot()` returned `reason` strings carrying running counts → state-change emit on every event | Second 60s validation showed seq delta 19,980 / 55s | `_decision_shape` compares structural verdict only (overall + per-symbol verdict tuple). Periodic refresh emit is now time-based (`decision_emit_interval_s=10s`), caps disk write rate at ~6/min regardless of event throughput. |

**60s validation final state (all 3 fixes applied):**
- 5 emissions in 55s = exactly 10s cadence ✓
- RSS 91,217,920 → 91,217,920 (ratio 1.0 — zero growth) ✓
- Handles 426 → 426 (ratio 1.0 — zero leak) ✓
- Validator exit code 0 (clean shutdown on deadline) ✓
- 28/28 tests still pass post-fixes

**1h validation final state (TSSV commit `39a331e`):**
- `validator_exit_code: 0` (clean shutdown on 3600s deadline)
- `n_samples: 361`, `decision_seq_no.delta: 359` (~10s cadence)
- Handles: 426 → 426 (ratio 1.0 — **zero leak over 1h**)
- RSS: 91,148,288 → 33,775,616 (ratio 0.3706 — **RSS DECREASED** due to
  Windows working-set trim; peak only +0.94 MB above baseline)
- Throughput: 52,877.8 events/sec sustained → ~190 million events
  processed across the 1h (journal looped ~60×)
- Known cosmetic false-positive: `process_clean_exit: false` —
  pre-fix `_summarize` was in monitor's memory before commit
  `b2e872a` landed; `validator_exit_code: 0` is authoritative.

### Stage 4 — Explicit runtime determinism (PASSED — 5/5 in 15.64s)

- **TS_SignalValidator** commit `6a021bc` (test code) + `39a331e` (executed)

`tests/test_stage4_determinism.py` — **5/5 PASSED in 15.64s** via
`pytest -m stage4 -v`:
- `test_final_decision_state_identical` ✓
- `test_final_seq_no_identical` ✓
- `test_final_per_symbol_byte_identical` ✓
- `test_final_heartbeat_state_identical` ✓
- `test_three_consecutive_runs_all_identical` ✓ (triple-run convergence)

`conftest.py` registers the marker and skips it unless explicitly
requested. Default `pytest tests/` → 33 fast tests pass, 5 stage4
skipped.

Closes the operator-flagged "Stage 4 partial coverage" concern: Stage
1 proved logic determinism, Stage 3 proved atomic-write consistency,
Stage 4 now proves *full runtime* determinism (two consecutive
validator processes consuming the same inputs produce byte-identical
decision state).

### Stage 5 — Field stress supervisor harness (READY — operator-launchable)

- **TS_SignalValidator** commit `6a021bc` (2026-05-14)

`tools/stage5_setup/`:
- `validator_task.xml` — Windows Task Scheduler template. Key
  settings: RestartOnFailure (3 attempts × 2 min), MultipleInstancesPolicy=IgnoreNew
  (single-writer rule), StartWhenAvailable=true (missed-run handling),
  ExecutionTimeLimit=PT0S (continuous), BootTrigger + LogonTrigger.
- `heartbeat_stale_monitor.py` — external staleness watcher. Polls
  `heartbeat.json`, logs `events/stale_heartbeat.jsonl` on stale
  detection (with onset + recovery duration tracking). Polls faster
  during stale windows for prompt recovery detection.
- `STAGE_5_DISRUPTION_PLAN.md` — full 72h operator runbook with
  prerequisites, setup steps, 6-disruption schedule (kill / hibernate
  / cold boot / hard reset / sleep / soft shutdown at hours
  6/18/30/48/60/72), and 5 pass criteria.
- `README.md` — TL;DR + file index.

**Identity safety reminder enforced:** the plan invokes CLAUDE.md's
hard prohibition on scheduled-task identity changes — operator must
run `Trade_Scan/tools/scheduled_task_identity_smoke.ps1` in validate
mode before importing the XML.

---

## 4. What's not yet done (out of scope for Phase 7a)

| Item | Why deferred |
|---|---|
| Stage 2 1h run final summary commit | Waiting for in-flight bash task `brkzkokxv` to finish |
| Stage 4 execution (`pytest -m stage4 -v`) | Avoiding I/O contention with in-flight Stage 2 |
| Stage 5 72h field-stress execution | Operator decision — needs the machine for 72h, requires the disruption schedule to be followed |
| Per-event audit log (MismatchTracker port) | Production-grade alerting surface; Phase 7b/8 concern, not 7a |
| H2 basket vault adaptation for `_load_vault_strategy` | H2 vault is basket-shaped (per-leg); per-symbol shape is what the journal events reference. Stage 2/3/4 use the per-symbol path which is sufficient for the gate. Basket-aware adaptation is a Phase 7b/8 concern. |

---

## 5. Repo state summary

| Repo | Commits since Phase 7a session start | Latest |
|---|---|---|
| Trade_Scan | 7 (`5528ff1` → current) | `74fc9aa` SYSTEM_STATE Manual — Stage 2 harness + fixes |
| TS_SignalValidator | 6 (`25b5822` → current) | `6a021bc` Stage 4 test + Stage 5 supervisor harness |

Both pushed to origin/main. Working trees clean (only Stage 2's
in-flight `outputs/stage2_metrics.jsonl` is being appended to as the
1h run continues).

---

## 6. Next-session entry points

When you return to Phase 7a work, the natural sequence is:

1. **Read the Stage 2 1h `outputs/stage2_summary.json`** (in
   `TS_SignalValidator/outputs/`). If the flags are green (RSS growth
   < 1.5×, handles growth < 1.5×, decisions_emitted=true,
   validator_exit_code=0), Stage 2 PASSED.
2. **Run Stage 4:** `pytest -m stage4 -v` (in `TS_SignalValidator/`).
3. **If Stage 4 PASSED:** all code-level Phase 7a gates green. The
   remaining work is Stage 5 — operator-driven 72h field-stress
   following `tools/stage5_setup/STAGE_5_DISRUPTION_PLAN.md`.
4. **After Stage 5 PASSED:** Phase 7a is complete. The next concrete
   step is **Phase 7b** (TS_Execution shadow-read mode with
   `enable_validator_gating: false`) — that's a separate repo + a
   separate session.

---

## 6.5. Cleanup pass record (2026-05-15 weekend cleanup, in parallel with Stage 5 in flight)

While Stage 5 ran undisturbed, two cleanup passes landed (validator + monitor PIDs 13304, 15456 verified alive throughout).

**Cleanup pass 1 (Trade_Scan `398baeb`)** — root untracked, worktrees, state orphans:
- Deleted `archive/2026-05-11_tmp_cleanup/` (17 stale research artifacts)
- Moved `outputs/POST_FREEZE_GIT_AUDIT.md` → `outputs/system_reports/08_pipeline_audit/POST_FREEZE_GIT_AUDIT_2026_05_12.md` + committed
- Renamed + committed `outputs/system_reports/08_pipeline_audit/Future Pain Points.txt` → `FUTURE_PAIN_POINTS.md`
- Moved `pine_exports/` → `archive/pine_research_2026_05/`
- Pruned 3 worktrees + their orphan branches (angry-dirac, gifted-pasteur, xenodochial-spence — all confirmed zero in-flight commits, gifted-pasteur's commit was already cherry-picked as `a3ed557`)
- Removed `TS_SIGNAL_STATE/decisions/DRY_RUN_H2_PHASE7A_PLACEHOLDER/` + `heartbeats/.../PLACEHOLDER` orphans (May 13 placeholder, superseded by SHADOW_JOURNAL_REPLAY)

**Refactor pass (TSSV `066cae3`)** — DRY shared modules:
- NEW `TS_SignalValidator/atomic_io.py` — `atomic_replace_with_retry` was duplicated in `decision_emitter.py` + `heartbeat.py`. Single source of truth now.
- NEW `TS_SignalValidator/vault_lookup.py` — `base_strategy_id` + `find_latest_vault` were triplicated (signal_validator + replay_journal_port + Trade_Scan replay tool). Single source within TSSV; Trade_Scan's copy stays (cross-repo discipline) with a doc-comment pointer to the canonical version.
- 33/33 fast tests pass post-refactor; 5/5 Stage 4 determinism tests pass; end-to-end Stage 1 replay still SHA-256 `c1f5dd7d…` (byte-identical).

## 6.6. Phase 3 cleanup items requiring operator decision

These are the items that need explicit policy choices, not mechanical execution:

| | Item | Question for operator | Recommendation |
|---|---|---|---|
| 1 | ~~13 stale `claude/*` branches~~ | ~~Per-branch verification~~ | **CLOSED 2026-05-15.** All 13 verified + deleted. 11 had 0 commits ahead of main (safe). 1 (tender-khayyam) had a single `.claude/settings.local.json` commit — per-user local config, dead. 1 (vigilant-allen) had 5 NEWSBRK Phase 1+2 commits not on main; NEWSBRK was killed per RESEARCH_MEMORY closure entry. **Tagged the head as `archive/newsbrk-vigilant-allen` (pushed to origin) before deleting** — abandoned NEWSBRK research is recoverable from the tag if ever needed. 0 `claude/*` branches remain locally. |
| 2 | ~~**Phase 7a evidence JSONL retention**~~ | ~~Keep `outputs/shadow_journal_strategy_guard_reference.jsonl` (~700KB) + `TS_SignalValidator/outputs/shadow_journal_port_output.jsonl` (~700KB) + `outputs/stage2_metrics.jsonl` indefinitely as audit trail, OR archive after N months?~~ | **CLOSED 2026-05-15** (operator concurred with recommendation). Keep indefinitely. They're the *empirical evidence* for Phase 7a's pass criteria. Future audits reference them directly (sha256 cited in commit messages). Cost is small (~3 MB total). |
| 3 | ~~**VALIDATION_DATASET corpus retention**~~ | ~~When does `h2_validator_baseline_v1` retire? Same question for `shadow_journal_2026_04_to_05`.~~ | **CLOSED 2026-05-15** (operator concurred with recommendation). Per Section 1m-i, frozen corpora are *permanently* immutable — they don't retire while any decision file references them. Retire = create new corpus version side-by-side; old one stays for audit. No action; this is governance, not cleanup. |
| 4 | ~~**Audit doc consolidation** in `outputs/system_reports/`~~ | ~~Multiple audit-style docs accumulate per phase... Should we consolidate into a single rolling `SYSTEM_AUDIT_LOG.md`, or keep per-phase?~~ | **CLOSED 2026-05-15** (operator concurred with recommendation). Keep per-phase. Each doc is a snapshot of a specific moment; consolidation loses the "what did we know when" attribution. The folder structure (subdirs per concern area) already organizes them. |
| 5 | **`TS_Engine` sibling repo** | Verify still needed (parity-monitor system) or archive? | **DEFERRED to Mon 2026-05-18** (operator). Keep sibling repo in place until Stage 5 field-stress results are reviewed; the parity-monitor utility may inform the Phase 7b shadow-read decision. Re-evaluate post-Stage-5. |

## 7. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-14 | Decompose plan's 14-day gate into 5-stage battery | Property-level evidence > wall-clock evidence; shadow journal recovery made the validation-logic stages fast |
| 2026-05-14 | Treat retired shadow infrastructure as reference, port LOGIC into TS_SignalValidator | Respects the 2026-05-09 retirement commits while reusing proven logic |
| 2026-05-14 | New sibling corpus `shadow_journal_2026_04_to_05` instead of mutating `h2_validator_baseline_v1` | Section 1m-i invariant — frozen corpus immutability |
| 2026-05-14 | Stage 3 before Stage 2 ordering (operator-mandated) | Cheap fail-fast tests catch bugs in seconds before the 1h Stage 2 wastes wall-clock |
| 2026-05-14 | Time-based periodic emit (10s) instead of event-count-based | Caps disk write rate regardless of event throughput; aligns with antivirus tolerance on Windows |
| 2026-05-14 | Stage 4 added as 5th explicit stage | Operator-flagged that "implicit" coverage by Stages 1+3 was insufficient |
| 2026-05-14 | Stage 5 ordered last | Wall-clock-expensive (72h); only after cheap stages have confirmed validator correctness |
| 2026-05-15 | §6.6 items 2/3/4 closed; item 5 deferred to Mon | Operator concurred with retention/consolidation/governance recommendations as written. TS_Engine archive question deferred until Stage 5 results inform Phase 7b shadow-read planning. |

---

*Generated 2026-05-14 mid-session. Final commit lands after the 1h
Stage 2 run completes; this doc will be updated with the final
summary metrics.*
