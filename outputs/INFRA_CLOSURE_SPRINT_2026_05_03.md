# Infrastructure Closure Sprint — Report

**Date:** 2026-05-03
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
**Scope:** Close top three infrastructure blockers from `INFRA_BACKLOG_NEWS_EXECUTION` — INFRA-NEWS-001 (HIGH), INFRA-NEWS-009 (MEDIUM), INFRA-NEWS-006 (MEDIUM, read-only diagnosis only).

---

## TL;DR — Final framework-readiness verdict

**Question:** *Can we start a new event-driven family without repeating NEWS research friction?*

**Answer: YES.**

- **INFRA-NEWS-001 (`bar_hour` silent rejection):** FIXED. Engine-level fallback now derives `bar_hour` from the row index when the column is missing. 5/5 regression tests green.
- **INFRA-NEWS-009 (sweep slot collision):** FIXED. Collision error now surfaces the next free slot. New `tools/register_sweep_stub.py` CLI replaces direct YAML edits and routes through the existing collision-safe `reserve_sweep_identity` API. 5/5 regression tests green.
- **INFRA-NEWS-006 (PORT/MACDX duplication):** EXPLAINED. Diagnosis written. Severity downgraded from MEDIUM → LOW: it is intentional code reuse + a namespace mislabeling on one specific strategy, not an emitter or aliasing bug. No fix required for the framework itself; the discovery report's NEWS_AMPLIFIED count is off-by-one but that doesn't affect the surviving candidate's metrics. (Recommended cosmetic actions documented in the diagnosis report; not executed.)

All three of the highest-impact blockers are now closed at the framework level. A new event-gated family started tomorrow will not repeat the `bar_hour` zero-trades trap, will not silently overwrite sweep registrations, and won't be confused by the PORT/MACDX duplication.

---

## Task 1 — INFRA-NEWS-001: bar_hour auto-population

### Problem

`engines/filter_stack.py::session_filter` calls `ctx.require("bar_hour")`. If the column is missing from the bar row (because the strategy's `prepare_indicators` didn't set it), the require fails, the filter sets `bar_hour=None`, and **rejects every bar**. Result: silent zero-trades.

### Fix

Added a fallback in `session_filter` that derives `bar_hour` from `ctx.row.name.hour` when the column is missing. Only rejects when neither path resolves a value (true indeterminate state).

```python
# Fallback: derive from row index timestamp when column absent.
if bar_hour is None:
    try:
        row = getattr(ctx, "row", None)
        if row is not None and hasattr(row, "name") and hasattr(row.name, "hour"):
            bar_hour = int(row.name.hour)
    except Exception:
        bar_hour = None
```

Behavior:
- Column present → unchanged
- Column missing + DatetimeIndex available → derives from index, gate operates correctly
- Column missing + no usable index → still rejects (correct safe behavior; fix only adds a fallback, doesn't loosen the gate)

### Files changed

| File | Change |
|---|---|
| `engines/filter_stack.py` | +9 lines (fallback block in `session_filter`) |
| `tests/test_filter_stack_session_bar_hour.py` | NEW — 5 regression tests |

### Tests

```
tests/test_filter_stack_session_bar_hour.py
  test_bar_hour_fallback_from_index_excluded_hour     PASSED
  test_bar_hour_fallback_from_index_allowed_hour      PASSED  ← was the failure case before fix
  test_bar_hour_column_unchanged_behavior             PASSED
  test_bar_hour_column_present_excluded               PASSED
  test_bar_hour_truly_indeterminate_still_rejects     PASSED

5/5 PASSED
```

---

## Task 2 — INFRA-NEWS-009: Sweep slot collision detection

### Problem

Direct YAML edits to `governance/namespace/sweep_registry.yaml` (last-writer-wins) silently overwrite slots already claimed by other directives. Specifically: my Path A wrappers' S13/S14 stubs overwrote a pre-existing 30M directive's claim on idea 22 S13. The existing API path (`reserve_sweep_identity`) already had a collision check, but its error message did not surface the next free slot, and there was no canonical CLI / scripted way to reserve a stub manually that would route through the API.

### Fix

Two-part:

**(a)** `tools/sweep_registry_gate.py::reserve_sweep_identity` — extended `SWEEP_COLLISION` error message to include the next free slot for the affected idea.

```python
next_free_num = int(idea_block.get("next_sweep", _compute_next_sweep(sweeps)))
while f"S{next_free_num:02d}" in sweeps:
    next_free_num += 1
next_free_slot = f"S{next_free_num:02d}"
raise SweepRegistryError(
    f"SWEEP_COLLISION: idea_id='{idea_id}' sweep='{requested_key}' already allocated to "
    f"directive='{existing_directive}' hash='{existing_hash}'. "
    f"Next free slot for idea_id='{idea_id}': '{next_free_slot}'."
)
```

**(b)** New CLI helper `tools/register_sweep_stub.py` — wraps `reserve_sweep_identity` with placeholder hashes for stub registration. Hard-fails on collision and shows the next free slot. Replaces direct YAML edits as the canonical entry point.

```bash
# Auto-pick next free slot:
python tools/register_sweep_stub.py 64 64_BRK_IDX_30M_NEWSBRK_S99_V1_P00

# Reserve specific slot — HARD_FAILs if occupied:
python tools/register_sweep_stub.py 22 22_CONT_FX_15M_RSIAVG_TRENDFILT_S15_V1_P00 --slot S15
```

### Files changed

| File | Change |
|---|---|
| `tools/sweep_registry_gate.py` | +9 lines (next-free-slot computation in collision error) |
| `tools/register_sweep_stub.py` | NEW — collision-safe CLI helper |
| `tests/test_sweep_collision_detection.py` | NEW — 5 regression tests |

### Tests

```
tests/test_sweep_collision_detection.py
  test_collision_with_different_directive_hard_fails  PASSED
  test_collision_error_suggests_next_free_slot        PASSED
  test_same_identity_idempotent_no_collision          PASSED
  test_auto_advance_picks_next_free_slot              PASSED
  test_collision_at_specific_slot_with_existing_patch_sibling  PASSED

5/5 PASSED
```

### Procedural note

This fix protects the API path. Direct text edits to `sweep_registry.yaml` (e.g. via VS Code) still bypass it. The CLI helper provides the canonical alternative, but cultural / process enforcement is needed to actually use it. Suggested follow-up (not in this sprint): add a pre-commit hook that runs an integrity check on `sweep_registry.yaml` and refuses commits that introduce collisions.

---

## Task 3 — INFRA-NEWS-006: PORT/MACDX duplication

### Read-only diagnosis

Full diagnosis: [outputs/PORT_MACDX_DUPLICATION_DIAGNOSIS.md](outputs/PORT_MACDX_DUPLICATION_DIAGNOSIS.md)

### Verdict

**Intentional code reuse + namespace mislabeling.** Not aliasing, not emitter contamination, not a runtime bug.

| Path | Filesystem identity | Real source-code identity |
|---|---|---|
| `strategies/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/` | PORT (idea 05) | Self-described as `54_STR_XAUUSD_5M_MACDX_S22_V1_P00` in its own docstring; uses MACDX indicators (`macd`, `ema_cross`) |
| `strategies/54_STR_XAUUSD_5M_MACDX_S22_V1_P04/` | MACDX S22 P04 | Author explicitly designed it to be byte-identical to MACDX S22 P00 (instrumentation overlay, no trading-decision change) |

`check_entry` is byte-identical between the two files. Trade lists are byte-identical because the trading logic is byte-identical.

### Severity downgrade

Original: MEDIUM (suspected emitter or aliasing bug).
Revised: **LOW** (one strategy was authored under the wrong idea/model token; the deeper P04 vs P00 sameness is by design).

### Affects future families?

Only if someone repeats the pattern of copying a strategy into another idea's folder without updating identity metadata. Not a systemic risk.

### Recommended cosmetic actions (not executed)

1. Rename or deprecate the mislabeled `05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/` folder. Three options listed in the diagnosis; user's call.
2. De-dup the discovery report's NEWS_AMPLIFIED count (currently shows two PORT/MACDX rows that are the same underlying strategy).
3. Add a discovery-time guard that warns on duplicate trade lists across distinct strategy names (single-line pandas check).
4. In any Phase 3 follow-up, refer to the surviving NEWS_AMPLIFIED candidate as **"MACDX S22 (XAU 5M)"** rather than "PORT XAU 5M".

---

## Validation — full framework regression

```
$ python -m pytest tests/test_admission_race_stabilization.py \
                   tests/test_classifier_gate.py \
                   tests/test_filter_stack_session_bar_hour.py    # NEW
                   tests/test_sweep_collision_detection.py        # NEW
                   tests/test_engine_resolver_policy.py \
                   tests/test_engine_integrity_canonical_hash.py \
                   tests/test_integrity_uses_resolver.py
======================== 67 passed, 1 failed in 2.32s ========================
FAILED tests/test_classifier_gate.py::test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior
```

The 1 failure is the documented `INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK` — pre-existing on `FRAMEWORK_BASELINE_2026_05_03`, unchanged by this sprint.

### Hash integrity vs FRAMEWORK_BASELINE_2026_05_03

```
OK     tests/test_admission_race_stabilization.py
OK     tests/test_classifier_gate.py
OK     tools/approval_marker.py
OK     tools/classifier_gate.py
OK     tools/orchestration/pre_execution.py
OK     tools/strategy_provisioner.py
OK     governance/preflight.py
OK     tools/reset_directive.py

VERIFIED: no hash drift in baseline-manifest files
```

All 8 anchored framework files unchanged.

### Intended drift (files modified by this sprint, not in baseline manifest)

```
fd9a7eb99bf1f2e4  engines/filter_stack.py            (Task 1: bar_hour fallback)
140d1f15dd1b7a2b  tools/sweep_registry_gate.py       (Task 2: collision error message)
34cad30feeed01e9  tools/register_sweep_stub.py       (Task 2: NEW CLI)
ccdb9841bf772be4  tests/test_filter_stack_session_bar_hour.py  (NEW)
abf9c6e4e4a7adfd  tests/test_sweep_collision_detection.py      (NEW)
```

These changes are intentional and confined to non-baseline files. The `FRAMEWORK_BASELINE_2026_05_03` lock is still valid.

---

## Updated INFRA backlog status

| ID | Severity | Status after sprint |
|---|---|---|
| INFRA-NEWS-001 | HIGH | **CLOSED** (Task 1) |
| INFRA-NEWS-002 | MEDIUM | OPEN |
| INFRA-NEWS-003 | MEDIUM | OPEN |
| INFRA-NEWS-004 | LOW | OPEN |
| INFRA-NEWS-005 | MEDIUM | OPEN |
| INFRA-NEWS-006 | ~~MEDIUM~~ → LOW | **EXPLAINED** (Task 3, severity downgraded) |
| INFRA-NEWS-007 | LOW | OPEN |
| INFRA-NEWS-008 | LOW | OPEN |
| INFRA-NEWS-009 | MEDIUM | **CLOSED** (Task 2) |

The remaining 6 OPEN items are MEDIUM/LOW operational papercuts that don't block a new event-gated family — they affect specific edge cases (contract ID copy-trap, schema extension procedure, reset_directive admin-edit workaround discoverability, registry orphan GC, idea_registry closure tracking, strategy directory drift on reset). Each has documented fix recommendations.

---

## Final framework-readiness verdict

**Can we start a new event-driven family without repeating NEWS research friction?**

**YES.** The three highest-impact blockers are closed:
- ✅ `bar_hour` silent rejection (HIGH) — fixed at engine level
- ✅ Sweep slot collision (MEDIUM) — fixed in API + canonical CLI replaces direct YAML edits
- ✅ PORT/MACDX duplication (MEDIUM→LOW) — explained, not a framework bug

Race-class framework remains stable: `FRAMEWORK_BASELINE_2026_05_03` lock holds (8/8 hashes intact). 67/68 regression tests pass; the 1 known failure is the pre-tracked `INFRA_BACKLOG_001`.

The remaining 6 OPEN backlog items are LOW/MEDIUM convenience issues that may eventually warrant attention but **do not block** the next event-gated family.

---

## What I did NOT change

- No commits made — work is in worktree + main checkout, unstaged.
- No edits to `idea_registry.yaml` or to placeholder-hash stubs in sweep_registry (per "no manual state editing" / out of sprint scope).
- No edits to baseline-manifest files (verified via hash check).
- No new strategies, directives, or research artifacts.
- No deletion of the mislabeled PORT folder (read-only diagnosis only).

---

## Files in this sprint (worktree + main are mirrored)

### Modified
- `engines/filter_stack.py` — bar_hour fallback
- `tools/sweep_registry_gate.py` — collision error next-free-slot

### Created
- `tools/register_sweep_stub.py` — collision-safe CLI
- `tests/test_filter_stack_session_bar_hour.py` — 5 INFRA-NEWS-001 tests
- `tests/test_sweep_collision_detection.py` — 5 INFRA-NEWS-009 tests
- `outputs/PORT_MACDX_DUPLICATION_DIAGNOSIS.md` — INFRA-NEWS-006 diagnosis
- `outputs/INFRA_CLOSURE_SPRINT_2026_05_03.md` — this report

### Unchanged (verified by hash)
- All 8 `FRAMEWORK_BASELINE_2026_05_03` anchored files

---

## Anchor reference

- Framework baseline tag: `FRAMEWORK_BASELINE_2026_05_03` → commit `afeda0a`
- Closure-sprint cleanup base: `4c8b9d0`
- This sprint: uncommitted in worktree
