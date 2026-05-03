# Classifier Gate Sweep-Scoping — Implementation Plan

**Status:** AWAITING APPROVAL (Protected Infrastructure under Invariant #6)
**Author:** session 2026-05-03
**Files touched:** `tools/classifier_gate.py` (+~20 LoC), `tests/test_classifier_gate.py` (+4 cases), `governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md` (new migration note)
**Estimated effort:** 30–45 min including tests.

---

## Problem

The classifier gate groups priors by `(MODEL_TOKEN, ASSET_CLASS)` only. Every cross-architecture exploration sweep (NEWSBRK A1+A2, ZREV multi-architecture, KALFLIP variants, etc.) puts mixed-indicator siblings into one bucket. The gate then picks the most-recent-mtime sibling as "prior," classifies the indicator delta as SIGNAL, and demands strict `cur_sv > prior_max_sv` — which is **mathematically unsatisfiable** when N siblings sit in `active_backup` simultaneously at any sv configuration.

Symptom: every multi-architecture batch sweep deadlocks at admission and forces serial single-sweep submissions or repeated sv bumps. This sprint already cost ~3 hours of friction on NEWSBRK; it will recur on every future cross-architecture family.

The narrowing primitive that fixes this already exists in the same file (`_find_prior_matches_narrowed`, lines 225–275), scoping priors to `(family, timeframe, sweep)` — but it only activates for ENGINE reruns.

## Proposed change

Apply structural narrowing to **all** admissions when the current directive has a structured name matching the sweep pattern (already enforced by the namespace gate for new submissions). Unstructured legacy directives keep the wide `(model, asset_class)` matching for back-compat.

### New semantics

> A directive's lineage is its sweep slot. `S03_V1_P00 / P01 / P02` are generations of each other. `S04_V1_P00` is a parallel exploration, not an ancestor of S03. SIGNAL classification + strict-greater check applies WITHIN a sweep, not across the family.

### Code change (one function, one branch)

`tools/classifier_gate.py::_find_prior_matches_narrowed`:

```python
# Current (lines 246-275):
engine_rerun = _is_engine_rerun(current_directive)
wide = _find_prior_matches(...)
if not engine_rerun:
    return wide   # ← unconditional wide for non-engine paths
...

# Proposed:
engine_rerun = _is_engine_rerun(current_directive)
wide = _find_prior_matches(..., allow_same_stem=engine_rerun)
if not wide:
    return wide
cur_id = _extract_structural_identity(current_directive)
if cur_id is None:
    return wide   # ← unstructured legacy directives keep wide matching
narrowed = [t for t in wide if _same_sweep_lineage(t, cur_id)]
# ENGINE rerun: empty narrowed → first-of-kind PASS (existing behavior)
# Normal admission: empty narrowed → also first-of-kind PASS (NEW)
return narrowed
```

The single behavior change is the last line: previously `return narrowed if narrowed else wide` for non-engine paths; now always `return narrowed`. ENGINE rerun semantics unchanged.

## Backward compatibility

| Scenario | Current behavior | After change | Notes |
|---|---|---|---|
| Within-sweep patch (P00 → P01 SIGNAL change, no sv bump) | BLOCK | BLOCK | Real governance value preserved |
| Within-sweep patch (P00 → P01 PARAMETER only) | PASS | PASS | Unchanged |
| Cross-sweep parallel exploration (S03 vs S04, different indicators) | BLOCK (deadlock) | PASS | The fix |
| ENGINE rerun (same directive, new engine) | PASS via narrowed | PASS via narrowed | Unchanged |
| Unstructured legacy directive name | PASS/BLOCK via wide | PASS/BLOCK via wide | Falls back, no break |
| First directive in a brand-new sweep slot | PASS (first-of-kind) | PASS (first-of-kind) | Unchanged |
| Indicator-hash silent-change (Rule 3, same sv) within a sweep | BLOCK | BLOCK | Real governance preserved |
| Indicator-hash silent-change across sweeps | BLOCK | PASS | Acceptable: cross-sweep is exploration, not lineage |

The last row is the only loosening. Mitigation: the silent-change detector is most valuable within a lineage where someone might accidentally change an indicator's behavior expecting backwards-compatibility. Across sweep slots, divergence is intentional research design — that's the entire point of having distinct sweep slots.

## Test plan (5 new cases in `tests/test_classifier_gate.py`)

1. **`test_cross_sweep_parallel_exploration_passes`**
   Two structured directives in same `(model, asset_class)` but different sweep slots, one with `pre_event_range`, the other with `highest_high/lowest_low`. Same sv. Both PASS.

2. **`test_within_sweep_signal_change_still_blocks_without_sv_bump`**
   Two directives in the same sweep slot (S03_V1_P00 → S03_V1_P01) with SIGNAL indicator delta and same sv. P01 BLOCKED. Bump sv → PASS. Proves within-sweep discipline preserved.

3. **`test_engine_rerun_narrowing_unchanged`**
   Existing ENGINE-rerun test still passes; same-stem source directive in `completed/` still serves as baseline; cross-family priors still excluded.

4. **`test_unstructured_legacy_name_first_of_kind_pass`**
   Directive without `S0X_V0Y_P0Z` pattern (e.g., a hand-rolled `MY_TEST.txt`) produces empty `MODEL_TOKEN` so it never matches any prior bucket — always returns first-of-kind PASS. Confirms the new narrowing logic doesn't break this path (which is reached *before* narrowing applies).

5. **`test_same_sweep_silent_hash_drift_blocks`** *(added per review)*
   Two directives in the same sweep slot, identical indicator imports, identical sv. The `prior_indicators_hash_lookup` callable returns a *different* aggregate hash for the prior (simulating a silent edit to the indicator module's internals). Expected: BLOCK with `indicator_hash_delta_detected: True`. This is the highest-risk failure mode the new sweep-scoped model must protect — silent internal logic drift inside an indicator module that doesn't change its import path. The within-sweep narrowing must NOT cause Rule 3 to lose teeth.

Plus rerun the full existing `tests/test_classifier_gate.py` suite to verify no regression.

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cross-sweep indicator drift accidentally lands without review | Low | Each sweep is a deliberate research artifact authored from a directive template; sweep_registry already gates new sweep registration |
| Unintended PASS for some edge case in the structured-name pattern | Low | Test #4 covers fallback; `_extract_structural_identity` returns None for malformed names → wide matching preserved |
| Future flow that depends on cross-sweep blocking semantics | Very low | None known; gate is the only consumer of this comparison surface; grep confirms no other callers |
| Test fixtures break | Low | `tests/test_classifier_gate.py` already exercises ENGINE-rerun narrowing — same primitive being extended |

## Migration note

Write `governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md` documenting:
- The new sweep-scoped contract (what counts as "lineage")
- Why cross-sweep parallel exploration now PASSes
- How within-sweep discipline is preserved
- How to author a directive that intentionally invokes the wide-matching legacy path (don't use a structured name) — included for completeness only

## Implementation order

1. Write `governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md` (the contract, before the code).
2. Add the 4 test cases (red — they fail against current code).
3. Patch `_find_prior_matches_narrowed` (green — tests pass).
4. Run full `tests/test_classifier_gate.py` and `tests/test_admission_race_stabilization.py` — no regressions.
5. Run the 12-directive NEWSBRK matrix as live proof — expect 12/12 admit clean.
6. Mirror to main checkout, regenerate guard manifest.
7. Commit `framework: extend classifier-gate scoping to sweep lineage (eliminates cross-sweep deadlock)`.

## Acceptance criteria

- All 4 new tests + all existing classifier-gate tests pass.
- All 12 admission-race tests still pass.
- 12-directive NEWSBRK matrix admits 12/12 in a single `run_pipeline.py --all` without sv bumps, marker friction, or PIPELINE_BUSY.
- Migration SOP exists and accurately describes the new contract.

---

**Authorization needed:** explicit `APPROVED` on this plan before any code is written.
