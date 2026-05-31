# Pipeline Observability — Proposals R1 + Res1

**Date:** 2026-05-30
**Author:** session retro
**Status:** PROPOSAL — not for implementation until repeated-occurrence justification appears
**Trigger threshold:** ≥1 additional independent instance of the failure mode each proposal addresses
**Decision authority:** operator (Protected Infrastructure modification per CLAUDE.md Invariant #6)

This document parks two pipeline-observability proposals surfaced in the 2026-05-30 v2 cointegration session retro. Both are **propose-only**: each addresses a real but single-occurrence failure mode. The operator's standing guidance (2026-05-30) is that Protected Infrastructure changes need repeated-occurrence justification, not a single instance. If a second instance of either failure mode surfaces, this doc becomes the starting point for the implementation plan.

---

## R1 — Engine-side admission rejections leave no ledger trace

### Problem statement

When the basket pipeline dispatches a directive to the engine and the engine rejects it at runtime (e.g., `pine_ratio_zrev_v1.py:215` raises `RuntimeError` when `len(common_idx) < 2 * n_window`), the dispatch produces NO `cointegration_sheet` row, NO `rejected_runs` row, and no clear log signal beyond the bare exception trace. The `completed/` directory tick goes up (the directive ran to terminal state) but the ledger row count does not.

### Discovery context

2026-05-30 v2 cointegration corpus run. 488 directives in `completed/`, 473 rows in `cointegration_sheet` (filtered by `methodology_version='v2_log_eg'`). Delta of 15 was invisible to corpus accounting. Operator-prompted audit (`tools/...`) revealed all 15 were ≤3-day windows hitting the engine's minimum-bars assertion. Without the operator's explicit audit request, the silent skip would have rolled forward as "we ran 488 v2 directives" — a corpus-completeness error nobody would catch.

### Proposed mitigation

When a basket dispatch terminates without a `cointegration_sheet` row, write a sibling REJECTED record. Two implementation paths, presented for completeness:

**Path A — `rejected_runs` sibling table (preferred for clean separation):**
- New table in `ledger.db` with columns: `run_id`, `directive_id`, `pair_a`, `pair_b`, `test_start`, `test_end`, `rejected_at_utc`, `reject_stage` (Stage 0.5 / Stage 1 / Stage 3 / engine runtime), `reject_reason` (verbatim exception message), `engine_version`, `engine_abi`
- Schema additive only; existing `cointegration_sheet` semantics unchanged
- Aggregator (`cointegration_aggregator.py`) cross-joins to produce a "completed but unscored" count alongside the WINNER/NEUTRAL/LOSER/BLOWUP buckets
- View: a new MPS tab "Rejected" surfaces the rejection in the operator workbook

**Path B — `cointegration_sheet` REJECTED state (denser, less clean):**
- Add `regime_state='rejected_engine_minbars'` (or similar) values to the existing `regime_state` column on rows where the engine rejected
- Aggregator filters `regime_state` properly to exclude REJECTED rows from corpus accounting
- Simpler schema; lossier semantics (mixing "ran and produced metrics" with "rejected at stage X")

### Touchpoints

`tools/run_pipeline.py:_load_basket_leg_inputs` + `tools/basket_runner.py` (catch + record) + `tools/ledger_db.py` (Path A: new table DDL; Path B: enum on `regime_state`) + `tools/cointegration_aggregator.py` (exclude REJECTED from active-corpus counts).

### Risk + cost estimate

- **Risk surface:** modest. New write path on the failure leg only. Append-only invariant respected. The happy path is unchanged byte-for-byte.
- **Test coverage required:** unit tests for the REJECTED-writer + integration test that re-runs one of the 15 known-rejected directives and confirms the REJECTED row lands.
- **Effort:** ~1 day end-to-end (schema + writer + tests + aggregator update + MPS view).

### Promotion trigger

Promote this proposal to an implementation plan when **a second corpus run produces a silent-skip count >0**, AND the operator independently asks "where did the missing rows go?" Until then, the existing pattern (operator-prompted audit when corpus accounting diverges from completed/) covers the once-per-quarter cadence at acceptable cost.

---

## Res1 — Bulk admission failure has no pre-flight

### Problem statement

`tools/run_pipeline.py --all` dispatches every directive in `INBOX/` through the admission gates. When a class of misconfiguration causes all (or most) directives to fail at the same gate, the pipeline still iterates them all — emitting one log line per rejection plus, eventually, one actionable error message buried near the bottom. The operator must scan logs to discover the cause.

### Discovery context

2026-05-30 CR-EXIT-FIX. First v2 corpus had 527 directives, all generated with `exit = break_idx + 1`. All 527 were rejected at `window_validity_gate` for the same reason (end_date past last_coint_date). The orchestrator emitted 527 `DIRECTIVE_NOT_ADMITTED` lines + 1 actionable `[ORCHESTRATOR] Execution Failed: [WINDOW_VALIDITY_GATE] ...` near the bottom of the log. Time to diagnose: minutes of `grep` + `tail`. Time to fix: hours (generator revision + regen + re-run).

### Proposed mitigation

Add a pre-flight sample admission test BEFORE parallel-dispatching the rest:

1. After token-gate + reconciliation, before the parallel-dispatch loop, pick `min(5, N)` directives from `INBOX/`.
2. Run each through the full admission stack synchronously (window-validity, namespace, sweep-registry, rule-binding).
3. If **all 5 fail at the same gate with the same reject reason**, halt with a `BULK-REJECTION` summary line: gate name + reject reason + suggested fix (extracted from the gate's existing suggestion field where present, e.g., window_validity_gate emits `Suggested directive window: ...`).
4. If 1-4 of the 5 fail, proceed with parallel dispatch — single rejections are normal noise and don't indicate bulk misconfiguration.
5. If 5/5 pass, proceed with high confidence (the corpus is at least admissible).

### Touchpoints

`tools/run_pipeline.py` near the orchestrator entry — a new `_preflight_admission_sample(inbox_files, sample_size=5)` helper called before the dispatch loop. No changes to gates or runners.

### Risk + cost estimate

- **Risk surface:** very low. The pre-flight just runs the existing admission code synchronously on a sample; it cannot produce false-positive failures.
- **Test coverage:** mock a directive that fails at admission, confirm pre-flight raises with the right message. Mock a valid one, confirm pre-flight passes silently.
- **Effort:** ~half day end-to-end.
- **Overhead per real run:** ~5 admission gate calls × ~50 ms each = ~250 ms total. Negligible vs the 17 min wall clock of a typical v2 corpus run.

### Promotion trigger

Promote when **a second bulk-admission failure burns >1 minute of wasted dispatch time** OR when the operator independently expresses friction with the current "scan logs to diagnose" pattern. The CR-EXIT-FIX instance was the first observed case; the F1 gate-verify step in the generator (commit `f948415`) addresses the upstream generator-side variant of this problem, which may reduce the pipeline-side variant's frequency below the threshold of "worth building."

---

## Why both are parked

Each proposal addresses a real friction observed exactly once this session. The operator's 2026-05-30 caution applies: Protected Infrastructure changes (`tools/run_pipeline.py`, `tools/basket_runner.py`, `tools/ledger_db.py`) should be justified by repeated occurrences, not single events. The pattern preserved here is:

- **Once → document the failure + propose the mitigation (this doc).**
- **Twice → operator gates the proposal to implementation plan.**
- **Plan → atomic phases → break-tests → commit → push.**

This preserves engineering discipline (no speculative architecture) while ensuring the lesson isn't lost.

---

## Cross-references

- Retro report: `outputs/session_retros/SESSION_RETRO_2026-05-30.md` (R1 = §Robustness, Res1 = §Resilience)
- Transition snapshot: `outputs/system_reports/06_strategy_research/COINTEGRATION_V1_TO_V2_TRANSITION.md` §4.5 (the CR-EXIT-FIX history that motivates Res1)
- F1 gate-verify step (lands the GENERATOR-side variant of Res1's concern): `tools/generate_cointrev_v3_directives.py::_verify_gate_compatibility` (commit `f948415`)
- 488/473 audit (motivates R1): `COINTEGRATION_V1_TO_V2_TRANSITION.md` §4.5 + the per-directive table embedded there
- CLAUDE.md Invariant #6 (Protected Infrastructure modification authority)
