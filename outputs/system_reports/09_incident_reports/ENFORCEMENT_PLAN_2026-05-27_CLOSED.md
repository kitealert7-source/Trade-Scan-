# Enforcement Plan — Convert Advisory Conventions to Pipeline Gates

> **STATUS: CLOSED — COMPLETE 2026-05-28.** All 7 enforcement units landed:
> A rule-binding gate (44b9506) + A2 strict flip (7f10de6); B window-validity
> continuous-span gate (5b954bc); C intent memory-hints (e65f0da); D
> methodology-citation gate (3eb6371); E1 sheet-coverage CI (692485f) + E2
> registry state matrix + reconcile-authoritative cleanup (f4ceb51). Charter
> closed 2026-05-28 (0eb2021). Cross-cutting invariant: every gate is
> repo-local + deterministic — no `~/.claude` / env-path / external-state
> coupling. The advisory-bypass failure mode is solved structurally. The
> F1-F3 refactor backlog below is now unblocked but explicitly NOT started
> (next session = observe operational friction first).

**Created:** 2026-05-27
**Author context:** End of a long session that surfaced today's "all the tools but they're bypassed" failure mode.
**Governing principle:** `[[feedback_enforceable_mechanisms_only]]` — optional docs/conventions decay. Every proposal here must reduce to a hook, gate, validator, or CI test. No new advisory layers.

---

## TLDR

Today's mishap was caused by the agent (Claude) bypassing five separate advisory checks that all existed. Five hard gates close the door on the same failure modes. **Total effort: 8-10 hours across one or two sessions.** Suggested first task: **Enforcement A (directive-naming ↔ rule_name validator)** — smallest gate that catches the most expensive bypass.

This plan is the source of truth for that work. Start a session, read this, pick the next unstarted task, build the gate.

---

## Why this plan exists — today's failure modes

| # | What happened today | Cost | What was *supposed* to prevent it |
|---|---|---|---|
| 1 | Cloned wrong strategy template (`cointegration_meanrev_v1_2`) when the actual reference was `pine_ratio_zrev_v1`. Naming `COINTREV_V3_L30` looked like a variant of `COINTREV_V2_L252`. | 45 directive runs wasted + ~2 hr debug | `/rerun-backtest` skill exists. Never invoked. |
| 2 | Used fixed 2024-01-02 → 2026-05-27 calendar window. Should have been per-pair cointegrated window from the screener's history. | 12+ polluted directives across sessions | `feedback_test_window_must_match_signal_class` memory entry — advisory only. |
| 3 | Used governance verdict (FAIL/CORE/WATCH) as research evaluator. | Near-miss on retiring a strategy with real edge | `feedback_screening_rules_for_research` — advisory only. |
| 4 | Token dictionary not read before authoring directives. | ~30 min reverse-engineering naming | "MANDATORY FIRST STEP" comment in MEMORY.md — advisory only. The runtime token gate validates shape, not semantics. |
| 5 | `repair_integrity` and `lineage_pruner` silently ignored MPS::Baskets sheet. | 138 basket runs wrongly quarantined; recovery work | No coverage check between MPS schema and the tools. (Fixed in commit `544c361` today, but the pattern recurs.) |

Each row's right-hand column is advisory. The fix is to convert each to enforced.

---

## The Five Enforcements

### A — Directive-naming ↔ `rule_name` validator (admission gate)

**Closes:** Failure #1 (wrong strategy template).

**Mechanism:** YAML registry mapping directive-name fragments → expected `recycle_rule.name`. Gate at admission rejects mismatches.

**Files to create / modify:**
- New: `governance/namespace/directive_rule_binding.yaml`
- Modify: `tools/run_pipeline.py` admission phase — add a `_rule_binding_gate()` check between token gate and idea gate
- Tests: `tests/test_directive_rule_binding.py`

**Sketch:**
```yaml
# governance/namespace/directive_rule_binding.yaml
bindings:
  - pattern_substring: "_COINTREV_V2_L"
    rule_name: cointegration_meanrev_v1_2
    matches_examples:
      - 90_PORT_AUS200NAS100_15M_COINTREV_V2_L252__E001
      - 90_PORT_AUDJPYUSDCHF_15M_COINTREV_V2_4H_L1500_B01__E001
  - pattern_substring: "_COINTREV_V3_L"
    rule_name: pine_ratio_zrev_v1
    matches_examples:
      - 90_PORT_UK100USDJPY_15M_COINTREV_V3_L30
  - pattern_substring: "_PAIRX_S"
    rule_name: h3_spread
  - pattern_substring: "_RECYCLE_S"
    rule_name: h2_recycle
```

**Acceptance criteria:**
- ✅ A directive named `..._COINTREV_V2_L...` with `recycle_rule.name: pine_ratio_zrev_v1` is **rejected** at admission with a clear error message naming the expected rule.
- ✅ A directive matching no known pattern is **rejected** with "pattern not in registry; add to `directive_rule_binding.yaml` if intentional."
- ✅ Existing 274 MPS Baskets directives all pass against the new gate when re-validated.
- ✅ Test suite (gate tests) passes.

**Estimated effort:** 1-2 hours.

---

### B — Window-validity validator (admission gate)

**Closes:** Failure #2 (calendar-window vs per-pair-cointegrated-window).

**Mechanism:** For directives where `basket.cointegration_join.lookback_days` is set, the gate reads the SQLite `cointegration_daily` table for `(pair_a, pair_b, lookback_days)` and asserts the directive's `test.start_date` → `test.end_date` overlaps a continuous cointegrated regime ≥ some minimum fraction (default: 70% of the window is regime='cointegrated').

**Override path:** Operator can override via explicit `methodology_override` field with a documented reason. Override is logged.

**Files to create / modify:**
- Modify: `tools/run_pipeline.py` admission — add `_window_validity_gate()`
- Reuse: existing `cointegration.db` access (via `basket_data_loader` or similar)
- Tests: `tests/test_window_validity_gate.py`

**Acceptance criteria:**
- ✅ A directive with `cointegration_join.lookback_days=252` whose window includes <70% cointegrated days for that pair is **rejected** with a suggestion of the proper window range from the screener.
- ✅ A directive with `methodology_override: "..."` documented passes but logs a `[WARN] METHODOLOGY_OVERRIDE` line.
- ✅ Directives without `cointegration_join` field are unaffected.
- ✅ Test suite passes.

**Estimated effort:** 3-4 hours.

---

### C — Skill-routing UserPromptSubmit hooks

**Closes:** Failure #1 partially (skill not invoked) + future workflow drift.

**Mechanism:** Hooks in `~/.claude/settings.json` that fire on operator phrases matching known workflow patterns. Emit `[Skill hint]` system reminders the agent sees.

**Files to modify:**
- `~/.claude/settings.json` (per-user) OR `.claude/settings.json` (per-project)

**Sketch:**
```jsonc
{
  "hooks": {
    "UserPromptSubmit": [
      { "trigger": "(?i)(rerun|re-run|repeat|like yesterday|same as before|previous test|reference (the )?prior)",
        "skill_hint": "rerun-backtest" },
      { "trigger": "(?i)(test window|date range|backtest period|2 year|calendar)\\b.*(cointegrat|regime|aligned)",
        "memory_hint": "feedback_test_window_must_match_signal_class" },
      { "trigger": "(?i)(governance|CORE|WATCH|FAIL).*evaluator",
        "memory_hint": "feedback_screening_rules_for_research" }
    ]
  }
}
```

**Acceptance criteria:**
- ✅ Saying "rerun yesterday's tests" triggers `/rerun-backtest` skill hint.
- ✅ Saying "use a 2-year window" with "cointegrated" in same prompt surfaces the memory entry.
- ✅ Hints are visible in agent context at start of turn.

**Estimated effort:** 1 hour.

---

### D — Methodology-citation requirement (admission gate)

**Closes:** Failure #3 (governance-as-evaluator + memory entries not read pre-task).

**Mechanism:** For directives marked as part of a SWEEP or COHORT (via `directive.cohort_id` or similar), require a `methodology_citations: [feedback_X, feedback_Y]` field. Gate validates each citation exists in MEMORY.md or RESEARCH_MEMORY.md.

**Files to create / modify:**
- Modify: `tools/run_pipeline.py` admission — add `_methodology_citation_gate()`
- Tests: `tests/test_methodology_citation_gate.py`

**Acceptance criteria:**
- ✅ A sweep directive without `methodology_citations` field is **rejected**.
- ✅ A sweep directive citing `feedback_NONEXISTENT` is **rejected** with "citation not found in MEMORY.md or RESEARCH_MEMORY.md."
- ✅ Single-directive runs (not part of sweep) unaffected.
- ✅ Test suite passes.

**Estimated effort:** 2 hours.

---

### E — Sheet-completeness gate (CI test)

**Closes:** Failure #5 (Baskets-blindness in state lifecycle tools). Already retroactively fixed today in commit `544c361`, but the failure pattern can recur the next time someone adds a new MPS sheet.

**Mechanism:** Pre-commit / CI test that enumerates MPS sheet names and asserts each is handled by both `repair_integrity.py` and `lineage_pruner.py`. Fails CI when MPS schema gains a sheet not yet supported.

**Files to create:**
- `tests/test_state_lifecycle_sheet_coverage.py`

**Sketch:**
```python
def test_repair_integrity_handles_all_mps_sheets():
    mps_sheets = set(pd.ExcelFile(MPS_PATH).sheet_names) - {"Notes"}
    expected_in_module = mps_sheets - {"Notes"}  # Notes is preserved but not scanned
    # Inspect repair_integrity.py for references to each sheet name
    src = (PROJECT_ROOT / "tools/state_lifecycle/repair_integrity.py").read_text(encoding="utf-8")
    for sheet in expected_in_module:
        assert sheet in src, f"repair_integrity does not reference MPS sheet {sheet!r}"
    # Same for lineage_pruner
    src2 = (PROJECT_ROOT / "tools/state_lifecycle/lineage_pruner.py").read_text(encoding="utf-8")
    for sheet in expected_in_module:
        assert sheet in src2, f"lineage_pruner does not reference MPS sheet {sheet!r}"
```

**Acceptance criteria:**
- ✅ Test passes against current state (post commit `544c361`).
- ✅ Test fails if Baskets is removed from either tool's scope.
- ✅ Wired into pre-commit hook (or gate test suite at minimum).

**Estimated effort:** 1 hour.

---

## Priority + Order

| Order | Task | Effort | Rationale |
|---|---|---|---|
| 1 | **A** — Directive-naming ↔ rule_name validator | 1-2 hr | Smallest hard gate; catches the most expensive bypass (today's 45-run waste) |
| 2 | **E** — Sheet-completeness gate (CI test) | 1 hr | Quickest land; locks in today's commit `544c361` work |
| 3 | **C** — Skill-routing hooks | 1 hr | Low effort, high signal — catches workflow drift early |
| 4 | **B** — Window-validity validator | 3-4 hr | Heavier but addresses the methodology problem that recurred multiple times |
| 5 | **D** — Methodology-citation requirement | 2 hr | Catches a broader class of "memory entry not read" failures |

**Total estimate: 8-10 hours.** Comfortable for 1-2 sessions.

---

## Refactoring Backlog (F1-F3) — lower priority than A-E

These are not enforcement gates. They're hygiene work surfaced during the same session's code-size investigation. Three files in `tools/` have monster functions that complicate every future change to them — including the enforcement work above. **Do A-E first**; F-series only after.

Investigation findings (`tools/` total: 92,632 lines):

| File | Lines | Worst function | Verdict |
|---|---|---|---|
| `run_pipeline.py` | 1,700 | `_try_basket_dispatch` (309) + 3 others >100 lines | Extract `tools/basket_dispatch.py` |
| `run_stage1.py` | 1,399 | `main` (499) + `emit_result` (493) | Decompose in place |
| `basket_data_loader.py` | 1,032 | `load_basket_leg_data` (422) | Decompose into stages |

### F1 — Extract `tools/basket_dispatch.py` from `run_pipeline.py`

**Why first in the F series**: Cleanest module boundary. Six basket-handling functions form a coherent subsystem already conceptually separate from admission / lifecycle / validation logic. Today's failure modes were all in basket territory — easier reasoning if the code lives together.

**Functions to move:**
- `_try_basket_dispatch` (309 lines)
- `_load_basket_leg_inputs` (185 lines)
- `_synthetic_leg_data`
- `_PassthroughStrategy` class
- `_announce_run_engine` (basket-side dispatch)
- `_find_admitted_directive_path` (used by basket dispatch)

Total extracted: ~600 lines. `run_pipeline.py` drops to ~1,100.

**Mechanism**: byte-equivalent extraction. New module imported by `run_pipeline.py`. No behavior change.

**Files to create / modify:**
- New: `tools/basket_dispatch.py`
- Modify: `tools/run_pipeline.py` (delete extracted functions, add import)
- Modify: `tools/tools_manifest.json` (regenerate hash for run_pipeline.py)
- Tests: existing gate test suite must continue to pass; add a smoke test that runs a single basket directive end-to-end

**Acceptance criteria:**
- ✅ All 70 gate tests pass at HEAD.
- ✅ A smoke directive (one basket pair, small window) runs through `run_pipeline.py --all` and produces the same MPS row as before extraction (byte-equivalent metrics).
- ✅ `tools_manifest.json` regenerated and committed in the same commit.
- ✅ `run_pipeline.py` line count drops to ~1,100.

**Estimated effort:** 2-3 hours.

---

### F2 — Decompose `basket_data_loader.load_basket_leg_data` (422 lines)

**Why second**: 41% of the file is one function. Today's basket-aware fixes had to reason around it indirectly. Future changes to basket data flow would benefit from clearer stages.

**Mechanism**: in-place decomposition into pipelined stages. No module split.

**Suggested stage breakdown** (subject to actual code review):
1. `_resolve_data_sources(parsed)` — symbol → CSV path lookup
2. `_load_raw_bars(symbol, tf, range)` — single-symbol CSV → DataFrame
3. `_align_legs(leg_dfs)` — intersect indices, handle holidays
4. `_join_cointegration_columns(out, parsed)` — auto-join screener columns (the section we now know well)
5. `_validate_loaded_data(out)` — sanity guards

Top-level `load_basket_leg_data` becomes ~80 lines of orchestration.

**Files to modify:**
- `tools/basket_data_loader.py` only

**Acceptance criteria:**
- ✅ All gate tests pass.
- ✅ A basket-runner smoke test produces identical per-bar parquet output before / after refactor (byte-equivalent).
- ✅ `load_basket_leg_data` top-level function drops to ≤100 lines.

**Estimated effort:** 2-3 hours.

---

### F3 — Decompose `run_stage1.py` `main` (499) + `emit_result` (493)

**Why last**: Most entangled. Two functions account for 71% of file. No clean module boundary; the work is internal restructuring of a single stage runner. Higher risk per unit of payoff vs F1 + F2.

**Mechanism**: in-place extraction of helpers. Same pattern as F2 but more extensive.

**Acceptance criteria:**
- ✅ All gate tests pass.
- ✅ A stage-1 smoke test produces identical run_state.json output before / after refactor.
- ✅ `main` and `emit_result` each drop to ≤150 lines.

**Estimated effort:** 4-6 hours.

---

## Combined effort estimate

| Phase | Tasks | Effort |
|---|---|---|
| Enforcement gates (priority) | A → E → C → B → D | 8-10 hours |
| Refactoring backlog (after enforcement) | F1 → F2 → F3 | 8-12 hours |
| **Total** | | **16-22 hours** (3-4 sessions) |

---

## What NOT to do (this is enforced too)

Per `feedback_enforceable_mechanisms_only`:
- ❌ **Don't add new advisory memory entries** about today's mishap. Memory has 5+ relevant entries already; another one decays into the pile.
- ❌ **Don't write a "best practices" doc** in `outputs/system_reports/`. Same problem.
- ❌ **Don't refactor existing tools for "clarity"** unless the refactor enables enforcement.
- ❌ **Don't extend `/session-close` or `/repo-cleanup-refactor` with optional checks.** Use hooks if you need automation; skill checklists decay.

---

## Pre-session prep (do BEFORE next session — by operator if possible)

- [ ] **Update MEMORY.md** with one-liner: "COINTREV_V2 = `cointegration_meanrev_v1_2`, COINTREV_V3 = `pine_ratio_zrev_v1`. V doesn't mean version; it means strategy class." (Until A lands and obsoletes the question.)
- [ ] **Verify git working tree is clean** before starting (it is, as of today's session close).
- [ ] **Read this document** + skim `feedback_enforceable_mechanisms_only` and `feedback_test_window_must_match_signal_class` for grounding.

---

## Reference: today's commits

- `544c361` — state_lifecycle: extend repair_integrity + lineage_pruner to cover Baskets
- `12455b9` — state_lifecycle: drop polluted + loss-making basket directives
- `478389b` — state_lifecycle: drop residual orphan strategy files

These are the "fix what we broke today" commits. The plan above is the "make sure today doesn't happen again" work.

---

## How to use this document in next session

1. Run `/session-start`. The Active Charter pointer in SYSTEM_STATE.md will surface this plan.
2. Open this file. Pick the lowest-numbered task not yet marked complete.
3. Read its "Files to create / modify" + "Acceptance criteria" sections.
4. Implement, test (gate test suite should pass at each commit), commit.
5. Mark the task complete here (edit this file), commit the doc update.
6. Move to the next task.

When all five enforcements land:
- Today's class of failure becomes impossible (or audited via override).
- This document becomes a historical artifact — close it out by archiving to `outputs/system_reports/09_incident_reports/ENFORCEMENT_PLAN_2026-05-27_CLOSED.md`.

---

## Author note

This plan was written immediately after a frustrating session where five separate enforceable rules existed only as advisory. The plan exists to convert each one to a hook. If at any point during execution a sub-task starts feeling like "let's just add another doc" — stop, re-read `feedback_enforceable_mechanisms_only`, and either find the enforcement path or drop the sub-task.
