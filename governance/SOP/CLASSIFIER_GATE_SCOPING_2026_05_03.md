# Classifier Gate Sweep-Scoping Contract — Migration Note (2026-05-03)

## What changed

The classifier gate's prior-matching scope tightened from
`(MODEL_TOKEN, ASSET_CLASS)` to `(MODEL_TOKEN, ASSET_CLASS, FAMILY, TIMEFRAME, SWEEP)`
for any directive whose name follows the structured sweep pattern
(`<family>_<asset>_<timeframe>_<model>_S0X_V0Y_P0Z`). Directives with
unstructured names continue to use the wide scope for back-compat.

## Why

Cross-architecture exploration sweeps (multiple sweep slots in one family,
each with different indicator sets) deadlocked at admission: every
sibling at the same sv saw the others as the "prior", classified the
indicator delta as SIGNAL, and demanded a strict sv bump that no single
value could satisfy. This blocked legitimate parallel research patterns
(NEWSBRK A1+A2, ZREV multi-architecture, KALFLIP variants, etc.) and
forced serial single-sweep submissions or repeated sv escalation.

Symptom across recent sprints: every multi-architecture batch sweep cost
hours of manual sv juggling and reset_directive cycles. Root cause was
the gate treating sibling sweep slots as ancestors of each other rather
than as parallel exploration branches.

## The new contract

A directive's **lineage is its sweep slot**.

- `S03_V1_P00 → S03_V1_P01 → S03_V1_P02` are generations of each other.
  Indicator changes between them require an `signal_version` bump, just
  as before.
- `S03_V1_P00` and `S04_V1_P00` are **parallel explorations**, not
  generations. Different indicator sets are intentional research design.
  No sv comparison is enforced between them.
- A brand-new sweep slot (no priors in the same `(family, tf, sweep)`
  bucket) is **first-of-kind PASS**, even if other sweep slots in the
  same family already exist.

## What's preserved

| Invariant | Status |
|---|---|
| Within-sweep SIGNAL change requires sv bump | **Preserved** |
| Within-sweep silent indicator-hash drift requires sv bump (Rule 3) | **Preserved** — explicitly tested |
| UNCLASSIFIABLE deltas fail-closed | **Preserved** |
| ENGINE-rerun narrowing | **Unchanged** |
| First-of-kind PASS for the very first directive in a new model/asset bucket | **Unchanged** |

## What's loosened

The single behavioral change: **cross-sweep silent indicator drift no
longer blocks**. Acceptable because:

- Each sweep slot is a deliberate research artifact, authored from a
  template, with its own indicator selection by design.
- The sweep_registry already gates sweep-slot creation — no sweep
  appears without explicit registration.
- Within-sweep silent drift (the high-risk case for "I edited the
  indicator's internals and forgot to bump sv") still BLOCKS via Rule 3.

## Migration impact

- Existing structured directives: behavior changes only at admission of
  a new directive whose mtime-nearest prior is in a *different sweep
  slot*. Previously such admissions could BLOCK; now they PASS.
- Existing unstructured directives: no change.
- ENGINE reruns: no change.
- Existing test suite: no regression expected.

## How to author a directive that intentionally invokes the wide-matching legacy path

Use an unstructured name (one that doesn't match the
`<family>_<asset>_<tf>_<model>_S0X_V0Y_P0Z` pattern). The classifier
will fall back to wide `(model, asset_class)` matching and the original
strict-greater behavior. This path exists only for legacy directive
back-compat — new submissions should always use the structured pattern
enforced by the namespace gate.

## Code reference

- `tools/classifier_gate.py::_find_prior_matches_narrowed` — the single
  function changed.
- `tests/test_classifier_gate.py` — 5 new test cases cover the new
  contract surface.
- `governance/SOP/CLASSIFIER_GATE_SCOPING_PLAN_2026_05_03.md` — full
  implementation plan with risk analysis.
