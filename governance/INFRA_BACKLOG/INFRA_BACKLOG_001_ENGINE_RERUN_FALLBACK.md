# INFRA_BACKLOG_001 — ENGINE_RERUN_FALLBACK

**Status:** OPEN
**Opened:** 2026-05-03
**Severity:** LOW (test contradicts source; no functional regression)
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / commit `afeda0a`
**Owner:** unassigned

---

## Issue

`tests/test_classifier_gate.py::test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior` fails. The test was already failing on HEAD prior to commit `afeda0a` and was NOT introduced by the framework stabilization sprint.

The test's assertion contradicts the source code's own documented behavior at [tools/classifier_gate.py:267-274](tools/classifier_gate.py:267):

```python
# For ENGINE reruns: if the same-structure prior set is empty, there is
# no structurally comparable baseline → treat as first-of-kind (PASS).
# Do NOT fall back to the wide set; comparing an ENGINE rerun against a
# structurally different strategy (different family/TF/sweep) always
# produces UNCLASSIFIABLE verdicts for differences that predate the
# engine upgrade and are irrelevant to the engine-only change.
if engine_rerun:
    return narrowed  # empty list → evaluate() will PASS as first-of-kind
```

Source intent: ENGINE rerun + no same-identity prior → first-of-kind PASS.
Test assertion: ENGINE rerun + no same-identity prior → wide fallback to a structurally different prior.

One of them is wrong. The test name (`falls_back_to_wide`) implies the test expects fallback. The source comment says explicitly "Do NOT fall back to the wide set." Without git history on the test file pre-`e338553`, we cannot tell which was intended. The two have been in conflict for at least the duration of recent work.

## Proof it is pre-existing (not from sprint)

```bash
git stash  # remove sprint changes
python -m pytest tests/test_classifier_gate.py::test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior
# → FAIL on git HEAD before the sprint
git stash pop
```

Verified during the sprint; recorded in commit `afeda0a` and in [outputs/FRAMEWORK_STABILIZATION_PROOF_2026_05_03.md](outputs/FRAMEWORK_STABILIZATION_PROOF_2026_05_03.md).

## Why deferred

- Sprint scope was framework race elimination + classifier scoping. Resolving this contradiction would require deciding the *correct* ENGINE-rerun fallback semantics, which is product-shape work, not framework stabilization.
- No functional regression: ENGINE reruns work in production (cf. v1_5_8a transition). The test failure is a contract-vs-implementation mismatch in the test suite itself.
- Resolution requires either (a) updating the test to match documented source behavior, or (b) updating the source to match the test's expectation. Either path needs explicit decision on which behavior is correct, not an autonomous patch.

## What needs to happen to close

1. Decide canonical ENGINE-rerun semantics for the empty-narrowed-priors case:
   - **Option A**: First-of-kind PASS (matches current source). Update test to assert PASS with `prior_directive=None`, `classification='N/A'`. Rename test (`falls_back_to_wide_*` is now misleading).
   - **Option B**: Wide fallback (matches current test). Patch [tools/classifier_gate.py](tools/classifier_gate.py) to remove the `if engine_rerun: return narrowed` short-circuit, keeping `return narrowed if narrowed else wide`. Risks: ENGINE reruns may now compare against structurally-distant siblings, producing UNCLASSIFIABLE verdicts on legitimate filter/regime differences (the exact pathology the source comment was added to prevent).
2. Whichever direction: add migration note to [governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md](governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md) clarifying the contract.
3. Re-issue [outputs/framework_baseline/REGRESSION_MANIFEST.md](outputs/framework_baseline/REGRESSION_MANIFEST.md) with new file hashes and updated expected pass count (29 → all green).
4. Tag the resolved baseline as `FRAMEWORK_BASELINE_<resolution_date>`.

## Recommendation (record only — not a decision)

Option A is mechanically smaller and matches the source's existing comment, which was written deliberately to prevent UNCLASSIFIABLE-verdict false-positives. Option B re-opens that pathology. Most evidence points to A.

## References

- Anchor commit: `afeda0a`
- Anchor tag: `FRAMEWORK_BASELINE_2026_05_03`
- Source: [tools/classifier_gate.py](tools/classifier_gate.py)
- Test: [tests/test_classifier_gate.py:340](tests/test_classifier_gate.py:340)
- Migration SOP: [governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md](governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md)
- Sprint plan: [governance/SOP/CLASSIFIER_GATE_SCOPING_PLAN_2026_05_03.md](governance/SOP/CLASSIFIER_GATE_SCOPING_PLAN_2026_05_03.md)
- Sprint proof: [outputs/FRAMEWORK_STABILIZATION_PROOF_2026_05_03.md](outputs/FRAMEWORK_STABILIZATION_PROOF_2026_05_03.md)
