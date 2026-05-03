# Framework Baseline Regression Manifest — 2026-05-03 (Hardened)

**Anchor commit:** `4b2e0f3` (will be tagged below)
**Anchor tag:** `INFRA_HARDENED_BASELINE_2026_05_03`
**Supersedes:** `FRAMEWORK_BASELINE_2026_05_03` (anchor `afeda0a`) — historical
lineage only; the framework + infrastructure surface have both moved on.
**Created:** 2026-05-03
**Authority:** This manifest freezes the combined framework + infrastructure
regression surface. Any divergence in file hashes or test counts after this
date is, by definition, a regression and must be reconciled or explicitly
re-baselined.

---

## What changed since `FRAMEWORK_BASELINE_2026_05_03`

The original baseline froze admission-race + classifier-gate-scoping work.
This re-issued baseline adds the Final Hardening Sprint + H2 closure surface:

- **C1**: `config/state_paths.py` — worktree-safe repo discovery via marker triplet.
- **C2**: `tools/run_pipeline.py` — sha256 manifest tamper guard (mtime → content hash).
- **C3 + M5**: `tools/sweep_registry_gate.py` (new API), `tools/orchestration/pre_execution.py`, `tools/new_pass.py` — lock-protected sweep-registry writers, no more substring matching.
- **H2**: `tools/lint_encoding.py` (extended patterns + cp1252 stdout fix), 8 site fixes in `tools/orchestration/watchdog_daemon.py`, `tools/create_audit_snapshot.py`, `tools/capital/capital_broker_spec.py`, `tools/robustness/loader.py`.

Net delta: +4 test files, +48 tests, +6 production files newly tracked (one
existing file — `pre_execution.py` — got a new hash from the C3+M5 refactor).

---

## Scope

The regression surface now covers seven areas:

1. **Approval marker** — content-equality marker contract (sha256 of canonicalized strategy.py).
2. **Classifier gate** — sweep-scoped lineage matching, SIGNAL discipline, silent-hash-drift detection.
3. **Admission race** — auto-consistency, provisioner mid-flight rewrites, EXPERIMENT_DISCIPLINE checks, stranded-admission-ghost recovery.
4. **State paths (C1)** — worktree-safe `PROJECT_ROOT` / `STATE_ROOT` resolution + env-var overrides.
5. **Manifest hash guard (C2)** — sha256 content-equality on tools manifest at pipeline entry.
6. **Sweep registry writers (C3+M5)** — exact-match, lock-protected, idempotent registry updates.
7. **Encoding lint (H2)** — `read_text()` / `write_text()` / `open()` text-mode caught at staged-commit time.

---

## Frozen test files (sha256)

| File | sha256 | size |
|------|--------|------|
| `tests/test_admission_race_stabilization.py` | `d36b370239fd982d9483a78ac47ae5471195ef14b51341f4e89236698315cb91` | 12,406 |
| `tests/test_classifier_gate.py` | `8097045be122c1c441e00bb639711bc01652011416f143c4e89b7f697ccfe5d8` | 24,135 |
| `tests/test_lint_encoding_extended.py` | `fc2fa399c58b7c75d357b5ea1222ccf4b17cf7e5d0b74b49d9b48202f028b233` | 8,528 |
| `tests/test_manifest_hash_guard.py` | `e127daf6c6179686d9700d7fd8b45df6029c081b8fa310cd4fe4c9dda76b6486` | 6,430 |
| `tests/test_state_paths_worktree.py` | `3d0d018513b375f20937e6004f459e0d917d42a939f1f104dd6a4cf362e07e15` | 7,442 |
| `tests/test_sweep_registry_writers_hardened.py` | `ecee9290f64325e787a760b3849976972b2c1c4aa6d19165790758c20e46600c` | 11,875 |

## Frozen production files (sha256)

These are the files the test surface is verifying. Tampering with any of
them without updating both this manifest AND the corresponding test must
be treated as a regression.

| File | sha256 | size | Surface |
|------|--------|------|---------|
| `tools/approval_marker.py` | `fd9dccf6a0f39629ed0e6d899821db8236fb306b30aff1ca49fd9ce91c4691a9` | 3,685 | approval marker |
| `tools/classifier_gate.py` | `ac07351a68b62c41a6fe62f54a9f997812db096192e1240c1d6d896a8c253c65` | 18,018 | classifier gate |
| `tools/orchestration/pre_execution.py` | `98338cbefd15c4799f718e944a6a888cf1953af048a85fa2f8e4025a3b6e90b9` | 12,753 | admission race + sweep registry writer |
| `tools/strategy_provisioner.py` | `cff4d794043a53451307f778eb5e79ca31f4ad0c0c2ac8268943dfdc3bd81adc` | 18,477 | admission race |
| `governance/preflight.py` | `d5e3084108b1637c68bf53a220c7ed5e75a78702aab2fc410c1e1e588d88dbf0` | 41,113 | admission race / EXPERIMENT_DISCIPLINE |
| `tools/reset_directive.py` | `8f0b8660525bf5e3cbd9a8b3376bb777f930fe482ab5a7dc2520f7e620307408` | 17,924 | admission race |
| `tools/run_pipeline.py` | `b6acffabcb541f62fdbe25ea239a82307883865cbf1676508d0f33c9231e709e` | 40,446 | manifest hash guard |
| `tools/sweep_registry_gate.py` | `f41215fa28f80218fe8464d3c5618f4aa37af8bb4068ed66d22bda5f5dcec4a3` | 31,067 | sweep registry writers |
| `tools/new_pass.py` | `0075f3210173015a4349370715205106199b5ca878f355e08ac1d6a546889fb2` | 26,815 | sweep registry writers |
| `tools/lint_encoding.py` | `0c5b079746919bebca083cf8b4f70ebce924f5dea6afdbe663b12dc85c87c70b` | 6,401 | encoding lint |
| `config/state_paths.py` | `a19a82b3dcee27d74293c82d28d68d7da281384df6a8ba906d0661b61e930c9a` | 10,496 | state paths |

`pre_execution.py` hash changed since `FRAMEWORK_BASELINE_2026_05_03` (was
`d1569535...`, now `98338cbe...`) due to the C3+M5 refactor — direct write +
substring matching replaced with the canonical lock-protected
`update_sweep_signature_hash` API. The test surface for this change lives in
`tests/test_sweep_registry_writers_hardened.py`.

---

## Test inventory at baseline (77 collected, 76 expected to pass)

| Surface | File | Count | Status |
|---|---|---:|---|
| approval marker + admission race | `test_admission_race_stabilization.py` | 12 | 12 PASS |
| classifier gate | `test_classifier_gate.py` | 17 | 16 PASS, 1 FAIL (INFRA_BACKLOG_001) |
| encoding lint (H2) | `test_lint_encoding_extended.py` | 20 | 20 PASS |
| manifest hash guard (C2) | `test_manifest_hash_guard.py` | 8 | 8 PASS |
| state paths (C1) | `test_state_paths_worktree.py` | 10 | 10 PASS |
| sweep registry writers (C3+M5) | `test_sweep_registry_writers_hardened.py` | 10 | 10 PASS |
| **TOTAL** |  | **77** | **76 PASS, 1 FAIL** |

The single failing test is `test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior`,
documented in `INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK.md`. **It must remain
the only failure.** Any additional failure is a regression.

### Expected baseline result

```
======================== 76 passed, 1 failed in <2s ========================
```

---

## Reproduction

From the repository root:

```bash
git checkout INFRA_HARDENED_BASELINE_2026_05_03
python -m pytest \
  tests/test_admission_race_stabilization.py \
  tests/test_classifier_gate.py \
  tests/test_lint_encoding_extended.py \
  tests/test_manifest_hash_guard.py \
  tests/test_state_paths_worktree.py \
  tests/test_sweep_registry_writers_hardened.py
```

Expected: `76 passed, 1 failed`. The one failure is
`test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior`.

To verify file integrity against this manifest:

```bash
python -c "import hashlib; [print(f, hashlib.sha256(open(f,'rb').read()).hexdigest()) for f in [
  'tests/test_admission_race_stabilization.py',
  'tests/test_classifier_gate.py',
  'tests/test_lint_encoding_extended.py',
  'tests/test_manifest_hash_guard.py',
  'tests/test_state_paths_worktree.py',
  'tests/test_sweep_registry_writers_hardened.py',
  'tools/approval_marker.py',
  'tools/classifier_gate.py',
  'tools/orchestration/pre_execution.py',
  'tools/strategy_provisioner.py',
  'governance/preflight.py',
  'tools/reset_directive.py',
  'tools/run_pipeline.py',
  'tools/sweep_registry_gate.py',
  'tools/new_pass.py',
  'tools/lint_encoding.py',
  'config/state_paths.py',
]]"
```

Compare against the hashes table above.

---

## Regression policy

- **Acceptable**: A new test added on top of these — manifest must be re-issued with the new test counted and the new file hashes recorded.
- **Acceptable**: Resolution of `INFRA_BACKLOG_001` flips the failing test to PASS — manifest must be re-issued.
- **Regression**: Any of the 76 currently-passing tests starts failing.
- **Regression**: Any production file's sha256 changes without a corresponding test update + manifest re-issue.
- **Regression**: Test count drops below 77.

When a regression is detected, the responsible commit must either revert the
change or update this manifest with explicit justification. No silent drift.
