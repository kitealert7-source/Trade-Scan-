# Framework Baseline Regression Manifest — 2026-05-03

**Anchor commit:** `afeda0a`
**Anchor tag:** `FRAMEWORK_BASELINE_2026_05_03`
**Created:** 2026-05-03
**Authority:** This manifest freezes the framework's regression surface. Any
divergence in file hashes or test counts after this date is, by definition,
a framework regression and must be reconciled or explicitly re-baselined.

---

## Scope

Three test surfaces define the framework's contract:

1. **Approval marker** — content-equality marker contract (sha256 of
   canonicalized strategy.py).
2. **Classifier gate** — sweep-scoped lineage matching, SIGNAL discipline,
   silent-hash-drift detection.
3. **Admission race** — end-to-end stabilization of auto-consistency,
   provisioner mid-flight rewrites, EXPERIMENT_DISCIPLINE checks, and
   stranded-admission-ghost recovery.

The two test files cover all three surfaces.

---

## Frozen test files (sha256)

| File | sha256 | size |
|------|--------|------|
| `tests/test_admission_race_stabilization.py` | `d36b370239fd982d9483a78ac47ae5471195ef14b51341f4e89236698315cb91` | 12,406 |
| `tests/test_classifier_gate.py` | `8097045be122c1c441e00bb639711bc01652011416f143c4e89b7f697ccfe5d8` | 24,135 |

## Frozen production files (sha256)

These are the files the test surface is verifying. Tampering with any of
them without updating both this manifest AND the corresponding test must
be treated as a regression.

| File | sha256 | size |
|------|--------|------|
| `tools/approval_marker.py` | `fd9dccf6a0f39629ed0e6d899821db8236fb306b30aff1ca49fd9ce91c4691a9` | 3,685 |
| `tools/classifier_gate.py` | `ac07351a68b62c41a6fe62f54a9f997812db096192e1240c1d6d896a8c253c65` | 18,018 |
| `tools/orchestration/pre_execution.py` | `d1569535cccddd3d196a68fe6a56f3033bc37c958577f29c8833a672dfe054a2` | 12,813 |
| `tools/strategy_provisioner.py` | `cff4d794043a53451307f778eb5e79ca31f4ad0c0c2ac8268943dfdc3bd81adc` | 18,477 |
| `governance/preflight.py` | `d5e3084108b1637c68bf53a220c7ed5e75a78702aab2fc410c1e1e588d88dbf0` | 41,113 |
| `tools/reset_directive.py` | `8f0b8660525bf5e3cbd9a8b3376bb777f930fe482ab5a7dc2520f7e620307408` | 17,924 |

---

## Test inventory at baseline (29 collected, 28 expected to pass)

### `tests/test_admission_race_stabilization.py` (12 tests)

| # | Test | Surface |
|---|------|---------|
| 1 | `TestHashMarkerRoundtrip::test_marker_records_sha256` | approval marker |
| 2 | `TestHashMarkerRoundtrip::test_write_then_validate` | approval marker |
| 3 | `TestLegacyMarkerCompat::test_legacy_marker_mtime_fail` | approval marker |
| 4 | `TestLegacyMarkerCompat::test_legacy_marker_mtime_pass` | approval marker |
| 5 | `TestIdempotentRewriteContract::test_byte_identical_rewrite_after_approval` | admission race (CORE REGRESSION) |
| 6 | `TestGenuineContentChangeInvalidates::test_logic_change_invalidates_marker` | approval marker |
| 7 | `TestCrossProcessMarkerValidity::test_subprocess_validation_matches_in_process` | admission race |
| 8 | `TestAutoConsistencyWritesHashMarker::test_inspect_pre_execution_uses_canonical_helper` | admission race |
| 9 | `TestAutoConsistencyWritesHashMarker::test_inspect_preflight_uses_is_approval_current` | admission race |
| 10 | `TestAutoConsistencyWritesHashMarker::test_inspect_provisioner_refreshes_marker_after_write` | admission race |
| 11 | `TestAutoConsistencyWritesHashMarker::test_inspect_reset_directive_uses_is_approval_current` | admission race |
| 12 | `TestAutoConsistencyWritesHashMarker::test_inspect_reset_directive_handles_stranded_admission_ghost` | admission race |

### `tests/test_classifier_gate.py` (17 tests, 16 pass + 1 pre-existing fail)

| # | Test | Surface | Status |
|---|------|---------|--------|
| 1 | `test_pass_when_no_prior` | classifier gate | PASS |
| 2 | `test_block_when_signal_change_without_sv_bump` | classifier gate | PASS |
| 3 | `test_pass_when_signal_change_with_sv_bump` | classifier gate | PASS |
| 4 | `test_pass_on_parameter_only_diff` | classifier gate | PASS |
| 5 | `test_pass_on_cosmetic_only_diff` | classifier gate | PASS |
| 6 | `test_same_stem_prior_excluded_rerun_case` | classifier gate | PASS |
| 7 | `test_block_on_indicator_hash_drift_without_sv_bump` | classifier gate | PASS |
| 8 | `test_engine_rerun_narrows_to_same_timeframe_and_sweep` | classifier gate | PASS |
| 9 | `test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior` | classifier gate | **FAIL — pre-existing on HEAD; tracked as INFRA_BACKLOG_001** |
| 10 | `test_structural_narrowing_active_without_override_reason` | classifier gate (NEW contract) | PASS |
| 11 | `test_engine_rerun_still_matches_same_identity_prior` | classifier gate | PASS |
| 12 | `test_pass_when_indicator_hash_matches_and_no_signal_change` | classifier gate | PASS |
| 13 | `test_cross_sweep_parallel_exploration_passes` | classifier gate (sweep-scoping) | PASS |
| 14 | `test_within_sweep_signal_change_still_blocks_without_sv_bump` | classifier gate (sweep-scoping) | PASS |
| 15 | `test_engine_rerun_narrowing_unchanged` | classifier gate (sweep-scoping) | PASS |
| 16 | `test_unstructured_legacy_name_first_of_kind_pass` | classifier gate (sweep-scoping) | PASS |
| 17 | `test_same_sweep_silent_hash_drift_blocks` | classifier gate (silent drift) | PASS |

### Expected baseline result

```
======================== 28 passed, 1 failed in <2s ========================
```

The single failing test (#9) is documented in `INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK.md`.
**It must remain the only failure.** Any additional failure is a regression.

---

## Reproduction

From the repository root:

```bash
git checkout FRAMEWORK_BASELINE_2026_05_03
python -m pytest tests/test_admission_race_stabilization.py tests/test_classifier_gate.py -v
```

Expected: `28 passed, 1 failed`. The one failure is `test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior`.

To verify file integrity against this manifest:

```bash
sha256sum tests/test_admission_race_stabilization.py tests/test_classifier_gate.py \
  tools/approval_marker.py tools/classifier_gate.py \
  tools/orchestration/pre_execution.py tools/strategy_provisioner.py \
  governance/preflight.py tools/reset_directive.py
```

Compare against the hashes table above.

---

## Regression policy

- **Acceptable**: A new test added on top of these — manifest must be re-issued
  with the new test counted and the new file hashes recorded.
- **Acceptable**: Resolution of `INFRA_BACKLOG_001` flips test #9 from FAIL to PASS
  — manifest must be re-issued.
- **Regression**: Any of the 28 currently-passing tests starts failing.
- **Regression**: Any production file's sha256 changes without a corresponding
  test update + manifest re-issue.
- **Regression**: Test count drops below 29.

When a regression is detected, the responsible commit must either revert the
change or update this manifest with explicit justification. No silent drift.
