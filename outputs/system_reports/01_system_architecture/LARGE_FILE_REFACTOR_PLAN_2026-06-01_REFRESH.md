# Large File Refactor Plan — 2026-06-01 Refresh

**Refresh date:** 2026-06-01
**Prior plan:** [LARGE_FILE_REFACTOR_PLAN.md](LARGE_FILE_REFACTOR_PLAN.md) (2026-04-21)
**Method:** same as prior — `loc` excludes blank + pure-comment lines; structural counts via `ast`.
**Status:** **CLOSED 2026-06-01** — see § 0 below for the campaign outcome and the empirical evidence that closed it. The detailed proposals in §§ 3–8 remain in the document as the original analysis; they were not executed past Item #4 because the dependency evidence (§ 0.3) showed no further structural ROI.

---

## 0. Campaign Outcome — Closed 2026-06-01

> **What changed since the refresh was written.** The 4-item in-place decomposition backlog was authorized and completed (with one substitution at #4). After re-measurement and two follow-up audits (dependency graph + basket dependency surface), the operator declined to authorize any further structural moves — including the 8-module file split this refresh originally proposed in § 3.

### 0.1. In-place decomposition outcomes (Items 1–4)

All four items landed; each is byte-equivalent on adjacent test suites + the broader pytest baseline (16 acknowledged failures, unchanged from 2026-05-31).

| # | Target | Max-fn before | Max-fn after | Strategy | Status |
|---:|---|---:|---:|---|---|
| 1 | `_try_basket_dispatch` in `run_pipeline.py` | 358 | 123 | 6 phase helpers + slim orchestrator | landed |
| 2 | `run_batch_mode` in `run_pipeline.py` | 226 | 127 | 3 phase helpers + slim orchestrator | landed |
| 3 | `main` in `run_stage1.py` | 499 | 113 (now 140 incl. patch-lifecycle helper) | 7 phase helpers + slim orchestrator | landed |
| 4 | `emit_result` in `run_stage1.py` (substituted for the originally planned `leg_strategy_dispatch.py` extraction) | 493 | 140 | 7 phase helpers + slim orchestrator | landed |

The Item #4 substitution decision is itself worth recording: the original Item #4 was the first *file extraction* (`tools/pipeline/leg_strategy_dispatch.py`, ~155 LOC moved). At the post-#3 re-measurement gate, the data showed `emit_result` (493 LOC, repo-largest function at that point) was strictly higher ROI than a file move that would not change any max-fn. The operator substituted.

### 0.2. Re-measurement (post-#3 gate)

The original gate framing was "after items #1–#3 land, `run_pipeline.py` may drop to ~1050–1150 LOC without any file split." Actual:

| File | Before campaign | After items #1–#3 | Δ LOC | Max-fn Δ |
|---|---:|---:|---:|---:|
| `tools/run_pipeline.py` | 1422 | 1593 | **+171** | 358 → 152 (−58%) |
| `tools/run_stage1.py` | 929 | 1063 | +134 | 499 → 113 (−77%) |

**LOC went UP, not down**, because helper signatures + docstrings + per-helper lazy imports cost lines. The campaign's actual benefit was elsewhere: max-function size dropped 58–77 %. The "one giant function dominates the file" anti-pattern that originally motivated the campaign is now absent from both files. The post-#4 numbers preserve this — every top max-fn in `run_stage1.py` is now ≤ 140 LOC.

### 0.3. Dependency / ownership data — what closed the campaign

Two read-only audits were run after Item #4 to test whether further structural work was justified.

**Phase-1 dependency audit (2026-06-01):**
- 352 `.py` under `tools/` parsed via `ast`; 640 internal import edges across 229 importer modules and 206 imported modules.
- Top fan-in modules (the most-depended-on): `config.state_paths` (61), `config.path_authority` (59), `tools.pipeline_utils` (45), `tools.ledger_db` (31), `tools.system_registry` (16). These are the real kernels and their high fan-in is healthy.
- Top fan-out modules: `run_pipeline.py` (36, expected — it's the orchestrator), then `family_report`/`report_generator`/`promote_to_live` (13–14 each). No domain module accidentally became an orchestrator.
- **Cross-bucket import flows** revealed that `cointegration_*` files form a closed cluster (11 files but only 4 distinct internal targets reached) and the validation `verify_*`/`lint_*`/`validate_*`/`*_gate` files have low cross-bucket coupling. These are **organizational clutter, not structural failure** — moving them under subdirs would be cosmetic.
- The only cross-bucket edge with structural character was `recycle_rules → basket-flat` (12 edges). That signal alone would have justified the basket subsystem extraction the refresh originally proposed.

**Basket dependency surface audit (2026-06-01):**
- Drilled into the recycle_rules → basket edge to determine whether basket extraction was strategically important.
- Finding: 12 of 14 recycle_rules files import basket code. **Every one of them imports exactly one module** (`tools.basket_runner`) and **exactly two symbols** (`BasketLeg` always, `BasketRunner` sometimes). Top-1 share of recycle_rules → basket edges: **100 %**. Whole-module imports: 0.
- Across the broader graph, `basket_runner` is the dominant basket fan-in (13 importers); every other basket module has fan-in ≤ 6 with importers either inside the basket subsystem itself or peers using each other directly.
- **`basket_runner` is already a de-facto clean API.** Recycle_rules consumes the basket subsystem through a single-module, two-type interface. The 12-edge cross-bucket signal from § 0.3 phase-1 was not a tangle — it was a protocol kernel correctly used.

### 0.4. Verdict

> A future basket-subsystem extraction would be **cosmetic, not strategically important**. The boundary is already enforced by convention; moving files into `tools/basket/` would change import paths but not the dependency graph's shape.

By the same logic, the other "subsystem creation" candidates the refresh proposed (cointegration consolidation, validation consolidation, top-level cleanup) lack architectural backing in the dependency data. They remain valid as cosmetic cleanups, addressable when convenient, but they are not gated work.

**The campaign is closed.** The detailed proposals in §§ 3–8 below remain as the original analysis. They are not authorized for execution. Any future revisit must produce *new* evidence of structural failure — not LOC drift, not file count — to reopen this plan.

### 0.5. Optional zero-risk follow-on (not authorized)

One near-zero-risk move was identified in the basket surface audit: add `__all__ = ["BasketLeg", "BasketRunner"]` at the top of `tools/basket_runner.py` to make the de-facto API surface explicit at the file level. This is a single-line documentation/convention change, not a structural move, and was not authorized at the closure point. Recorded here for future reference.

---

## 1. Prior Plan Status — DONE

All five offenders from the 2026-04-21 plan have shipped:

| File | 2026-04-21 LOC | 2026-06-01 LOC | Delta | Status |
|---|---:|---:|---:|---|
| `tools/portfolio_evaluator.py` | 1732 | 334 | −1398 | refactored (slim entry; logic split per plan) |
| `tools/report_generator.py` | 1521 | 159 | −1362 | refactored |
| `tools/capital_wrapper.py` | 1493 | 173 | −1320 | refactored |
| `tools/promote_to_burnin.py` | 1325 | (deleted) | — | superseded (promote workflow now in `tools/promote/`) |
| `tools/format_excel_artifact.py` | 1069 | 37 | −1032 | refactored (presentation moved to `tools/excel_format/`) |

The prior plan is now historical. The methodology and named invariants still apply; nothing in this refresh contradicts them.

---

## 2. New Top Offenders (LOC ≥ 800)

Same audit method, rescanned `tools/` + `tests/` on 2026-06-01:

| Rank | File | LOC | fns | classes | max_fn | Severity |
|---:|---|---:|---:|---:|---:|---|
| 1 | `tools/run_pipeline.py` | 1422 | 36 | 2 | 358 | **HIGH** |
| 2 | `tools/cointegration_excel.py` | 1228 | 30 | 0 | 229 | **HIGH** |
| 3 | `tools/ledger_db.py` | 1120 | 37 | 0 | 179 | MEDIUM |
| 4 | `tools/idea_evaluation_gate.py` | 998 | 21 | 0 | 227 | MEDIUM |
| 5 | `tools/system_introspection.py` | 993 | 24 | 0 | 292 | MEDIUM |
| 6 | `tools/run_stage1.py` | 929 | 14 | 0 | **499** | MEDIUM ⚠ (giant function) |
| 7 | `tools/pre_promote_validator.py` | 861 | 41 | 3 | 217 | LOW |
| 8 | `tools/basket_hypothesis/basket_report.py` | 848 | 25 | 0 | 108 | LOW |
| 9 | `tools/basket_report.py` | 825 | 17 | 0 | 280 | LOW |
| 10 | `tests/test_family_report_phase_b.py` | 947 | 56 | 0 | 41 | n/a (test file) |

Only the top two cross the 1000-LOC threshold the prior plan used. **`tools/run_pipeline.py` is the only HIGH-severity item that didn't exist on the prior list — it grew there.**

---

## 3. tools/run_pipeline.py — Full Audit

- **LOC:** 1422 (1937 raw incl. blank/comment) — over the 1000 mark, under the 1500 critical threshold
- **Functions:** 36  **Classes:** 2 (small)
- **Max function:** `_try_basket_dispatch` (358 LOC — second-largest function in the repo after the report sections)
- **Second-largest:** `run_batch_mode` (226 LOC)
- **Third-largest:** `_load_basket_leg_inputs` (152 LOC) + `main` (132 LOC)
- **Classification:** MIXED_CONCERNS
- **Risk level:** HIGH

### 3a. Responsibility map (top-level definitions)

| Lines | Group | Members | LOC |
|---|---|---|---:|
| 65–217, 509–528, 720–735 | **A. Admission state machine** | `admit_directive`, `archive_completed_directive`, `reconcile_active_backup`, `recover_partially_admitted_directives`, `_find_admitted_directive_path`, `verify_directive_uniqueness_guard` | ~145 |
| 218–509 | **B. Startup guardrails** | `validate_inbox_directive_tokens`, `enforce_run_schema`, `gate_registry_consistency`, `verify_manifest_integrity`, `verify_indicator_registry_sync`, `_compute_manifest_file_hash`, `verify_tools_timestamp_guard` | ~330 |
| 529–636 | **C. Strategy drift** | `_normalize_strategy_lines`, `_multisymbol_drift_check`, `detect_strategy_drift` | ~100 |
| 637–718, 1479–1518 | **D. Error mapping + announcements** | `map_pipeline_error`, `_announce_run_engine`, `_report_data_freshness` | ~120 |
| 736–1094 | **E. Basket dispatch (heavy)** | `_try_basket_dispatch` (358 LOC) | ~360 |
| 1096–1252 | **F. Leg-strategy dispatch** | `_PassthroughStrategy`, `LegDispatchError`, `LEG_STRATEGY_DISPATCH` + helpers (R1 2026-06-01) | ~155 |
| 1253–1428 | **G. Basket leg inputs** | `_synthetic_leg_data`, `_load_basket_leg_inputs` | ~170 |
| 1429–1780 | **H. Batch runner** | `run_single_directive`, `_assert_pipeline_idle`, `run_batch_mode` | ~305 |
| 1781–1936 | **I. Main entrypoint** | `_parse_max_parallel`, `main` | ~155 |

Eight reasonably-coherent groups. Each is between 100 and 360 LOC. The two big functions (`_try_basket_dispatch` 358, `run_batch_mode` 226) both deserve internal decomposition before or during the split.

### 3b. Proposed split

| New module | Responsibility | Members | LOC |
|---|---|---|---:|
| `run_pipeline.py` (slim) | CLI entry, top-level orchestration | `main`, `_parse_max_parallel` | ~160 |
| `tools/pipeline/admission.py` | Directive INBOX → active_backup → completed lifecycle | group A | ~145 |
| `tools/pipeline/guardrails.py` | Startup integrity gates (token, schema, registry, manifest, indicator sync, tools-timestamp) | group B | ~330 |
| `tools/pipeline/strategy_drift.py` | Per-symbol / multi-symbol strategy drift checks | group C | ~100 |
| `tools/pipeline/error_mapping.py` | `map_pipeline_error`, engine + freshness announcements | group D | ~120 |
| `tools/pipeline/basket_dispatch.py` | `_try_basket_dispatch` + `_PassthroughStrategy` + `_synthetic_leg_data` | E + part of G | ~400 |
| `tools/pipeline/leg_strategy_dispatch.py` | `LegDispatchError`, `LEG_STRATEGY_DISPATCH`, `CONTINUOUS_HOLD_RULES`, `_build_*_legs`, `_dispatch_leg_strategies` | group F | ~155 |
| `tools/pipeline/basket_inputs.py` | `_load_basket_leg_inputs` (data + factor + leg strategies) | rest of group G | ~155 |
| `tools/pipeline/batch_runner.py` | Sequential / parallel batch loop + per-directive run | group H | ~305 |

Result: `run_pipeline.py` shrinks to ~160 LOC (just `main` + CLI), eight focused modules under a new `tools/pipeline/` package, each in the 100–400 LOC range. The R1 work (2026-06-01) already extracted group F's members to module scope — `pipeline/leg_strategy_dispatch.py` is the trivial first extraction (zero internal decomposition needed).

### 3c. Functions that need internal decomposition first

Before splitting, two functions should be cut down inside the current file (matches the prior plan's pattern of "decompose the long function, then move it"):

| Function | Current LOC | Decomposition |
|---|---:|---|
| `_try_basket_dispatch` | 358 | Split by phase: directive parse → rule-block construction → factor resolution → leg data load + strategy build → BasketRunner invocation → result write. Five sub-functions of ~70 LOC each. |
| `run_batch_mode` | 226 | Split into: per-batch setup + telemetry init → per-directive execution + status handling → cleanup + summary. Three sub-functions of ~75 LOC each. |

These two decompositions can land independently of the split — pure refactors with no API surface change.

### 3d. Notes / shared constraints

- **CLI stability is a contract** — exit codes + stdout shape are consumed by `governance/preflight.py`, the `outputs/.session_state/pipeline_telemetry/*.jsonl` writer, and the operator's `/execute-directives` skill. The slim `run_pipeline.py` MUST preserve them exactly; CLI tests in `tests/test_run_pipeline_*.py` should pass byte-equivalently.
- **Admission idempotency** is a named invariant — re-admission of an already-completed `directive_id` must continue to raise `Directive already executed`. The admission module's `verify_directive_uniqueness_guard` is the load-bearing check; keep its signature unchanged.
- **Leg-strategy dispatch invariant (R1, 2026-06-01)** must be preserved. The dispatch module's coverage test `tests/test_leg_strategy_dispatch.py::test_every_registered_rule_has_a_leg_strategy_assignment` walks `governance/recycle_rules/registry.yaml` — when the dispatch module moves, the test's import path moves with it, but the invariant must keep enumerating the same registry.
- **`tools_manifest.json` hash check** — every file move + every rename triggers `tools/lint_no_hardcoded_paths.py` and the timestamp guard. Plan to regen the manifest immediately after each module extraction.

### 3e. Suggested refactor order

1. **Decompose `_try_basket_dispatch` in place** (no file split yet). Lands as a same-file PR with the five sub-functions. Verify with the standard basket pilot run.
2. **Decompose `run_batch_mode` in place**. Verify with `--all` on an empty INBOX (fast) and on a one-directive INBOX.
3. **Extract `tools/pipeline/leg_strategy_dispatch.py`** — already module-scope from R1; near-zero-risk move. `tests/test_leg_strategy_dispatch.py` import path updates.
4. **Extract `tools/pipeline/admission.py`** — clean seams, no internal dependencies on other groups.
5. **Extract `tools/pipeline/guardrails.py`** — depends only on filesystem + governance reads.
6. **Extract `tools/pipeline/strategy_drift.py`** — independent.
7. **Extract `tools/pipeline/error_mapping.py`** — independent.
8. **Extract `tools/pipeline/basket_inputs.py`** — uses leg_strategy_dispatch.
9. **Extract `tools/pipeline/basket_dispatch.py`** — uses basket_inputs + leg_strategy_dispatch. Largest, do after dependencies are stable.
10. **Extract `tools/pipeline/batch_runner.py`** — uses admission + guardrails + basket_dispatch + error_mapping.
11. **Slim `run_pipeline.py`** to `main` + `_parse_max_parallel` only.
12. **Regen `tools_manifest.json`** once after the final state, not after every step (avoids twelve manifest commits).

### 3f. Effort

HIGH. Touch surface is the pipeline orchestrator — every directive run flows through this file. Requires:

- Golden-run regression: one full `--all` cycle (basket + non-basket) before and after, with byte-equivalent telemetry JSONL and identical exit codes.
- Existing test suites pass: `test_leg_strategy_dispatch.py` (11), `test_cointegration_view.py` (26), `test_cointegration_ledger_writer.py` (9). Broader pytest baseline (currently 16 acknowledged failures) must not gain new failures.
- The five integration points named in `[[mechanism-port-integration-points]]` memory (registry, dispatch, execution path, exports, governance) must be walked for each extracted module.

Estimated as a multi-session effort; not a single-session refactor.

---

## 4. Second-Tier — tools/cointegration_excel.py

- **LOC:** 1228, fns 30, classes 0, max_fn 229
- **Classification:** MIXED_CONCERNS (presentation + data fetch + structural metric compute)
- **Risk level:** HIGH (1000+ LOC, recently active surface during the cointegration v2 work)

Out of scope for this refresh's deep proposal — flagging only. Suggested approach mirrors the prior plan's `format_excel_artifact.py` split: `cointegration_excel.py` (slim CLI) + `cointegration_io.py` (DB reads) + `cointegration_metrics.py` (universe metrics) + `cointegration_excel_writer.py` (XLSX writer).

---

## 5. tools/run_stage1.py — Flag: 499-LOC function

- **LOC:** 929 (below 1000 threshold), but **max_fn 499 LOC** — a single function does the bulk of Stage-1 work
- **Risk level:** MEDIUM ⚠ (giant function is the prior plan's primary anti-pattern)

This file would benefit from the same internal-decomposition step (3c above) even without a full split. The 499 LOC function is the largest in the repo today.

---

## 6. Cross-Cutting Observations (refreshed)

- **The prior plan's `tools/` hotspot pattern still holds.** All current offenders are in `tools/`. `engine_dev/`, `governance/`, `indicators/` remain below 1000 LOC.
- **Pipeline orchestration is the new center of gravity.** Prior offenders were artifact writers (portfolio_evaluator, report_generator, format_excel_artifact). Now the largest file is the pipeline orchestrator itself. Different cost profile: artifact writers can split cleanly; orchestrators have stronger ordering constraints.
- **Same anti-pattern recurs:** one or two functions dominate file size. `_try_basket_dispatch` (358) + `run_batch_mode` (226) account for 41% of `run_pipeline.py`. The 989-LOC `generate_backtest_report` was the equivalent in the prior plan. *Decompose the long function before splitting the file.*
- **Recent integration-point hygiene gain.** The R1 invariant (`LegDispatchError` + registry-coverage test, 2026-06-01) means new recycle rules can no longer silently fall through dispatch. The basket-dispatch split below should preserve and strengthen that test.

---

## 7. Effort Summary

| File | Effort | Driver |
|---|---|---|
| `tools/run_pipeline.py` | HIGH | Pipeline orchestrator; 8-way split + 2 internal decompositions; golden E2E required |
| `tools/cointegration_excel.py` | MEDIUM | Presentation/metrics mix; 4-way split similar to format_excel_artifact |
| `tools/ledger_db.py` | MEDIUM | 37 small functions in one file; cohesive but big — review for natural sub-modules |
| `tools/run_stage1.py` | MEDIUM | 499-LOC function decomposition; same-file refactor before any split |
| Second tier (idea_evaluation_gate, system_introspection, etc.) | LOW–MEDIUM | Sub-1000 LOC; defer unless touched for other reasons |

## 8. Recommended Order

1. **In-place decompose `_try_basket_dispatch`** (358 → ~5 functions of ~70 LOC).
2. **In-place decompose `run_batch_mode`** (226 → ~3 functions of ~75 LOC).
3. **In-place decompose the 499-LOC function in `run_stage1.py`**.
4. **Extract `tools/pipeline/leg_strategy_dispatch.py`** — near-zero-risk first move.
5. Proceed through extractions 4–10 of §3e.
6. Then start `cointegration_excel.py` split (after `run_pipeline.py` stabilizes — avoids touching two big surfaces simultaneously, per the prior plan's discipline).
7. `ledger_db.py` and `run_stage1.py` last — both are stable surfaces with strong contracts; defer unless they grow further.

---

## Artifacts

- This refresh: `LARGE_FILE_REFACTOR_PLAN_2026-06-01_REFRESH.md`
- Prior plan (retained as history): `LARGE_FILE_REFACTOR_PLAN.md` (2026-04-21)
- Audit CSV: regen via the same script the prior plan used (locate or re-author)
