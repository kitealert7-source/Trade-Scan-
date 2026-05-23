# Weekly maintenance retrospective — 2026-05-22

First time the four-skill weekly maintenance cycle (`/pipeline-state-cleanup` → `/repo-cleanup-refactor` → `/system-health-maintenance` → cleanup-backlog follow-ups → `/session-close`) ran end-to-end. This document captures every friction surfaced and observation made during the session, the disposition of each, and the recommended skill / process tunings for the next weekly cycle.

---

## Frictions (10 surfaced, by cost)

### High-cost — caused real backtracking

**F1 — Wrong diagnosis of "FSP integrity drift" (methodology).** I theorized `repair_integrity.py` was incomplete (missing FSP audit). The chip's investigation showed `repair_integrity.py` audits both ledgers correctly; the bug was a self-inconsistency in `lineage_pruner.py::verify_referential_integrity()` (global tally counted only `runs/`, per-run check accepted `runs/ OR sandbox/`). Acting on the original framing would have destroyed 96 valid FSP rows in an append-only ledger.

- **Resolved:** chip commit `aa679fd` (3-line patch in the checker, zero ledger touches); backlog Item 5 retracted.
- **Captured:** `feedback_audit_checker_before_ledger.md` (chip-authored).

**F2 — Smoke fixture rotted faster than the pipeline.** Multiple gates fail: VOLEXP Idea Gate (governance drift), wrong RUNS_DIR cleanup path (state-paths convention drift), missing `repeat_override_reason`, stale indicator list, and per the chip's note still fails at F1/F11/Strategy-Drift gates.

- **Resolved partially:** chip commits `b7f602a` (override) + `5264590` (path fix); broader STRATEGY_AUTHORITY_DIR refactor reverted as deferred.
- **Still open:** smoke fixture rebuild (proper directory split + tracked fixture strategy.py + indicator policy alignment).
- **Captured:** `feedback_smoke_fixture_decay.md`.

**F3 — Cross-repo work blocked by sibling repo state.** Item 4 (TS_Execution archive move) deferred because TS_Execution had 7 uncommitted modifications + 1 untracked file + 5 `claude/*` outstanding branches.

- **Resolved (the work deferred cleanly):** Backlog Item 3 annotated; the cross-repo move waits for sibling cleanup.
- **Captured:** `feedback_cross_repo_preflight.md`.

### Medium-cost — slowed work, didn't reverse it

**F4 — `/pipeline-state-cleanup` Phase 1 referenced a non-existent script** (`tmp/hydrate_sandbox.py`).

- **Resolved:** Skill SKILL.md updated (Phase 1 removed, Phases 2–5 → 1–4), friction-logged.

**F5 — Master_Portfolio_Sheet.xlsx open in Excel silently blocked Phase 2.** Skill doesn't preflight for file locks.

- **Resolved (the symptom, not the root):** operator closed Excel and re-ran.
- **Open for next pass:** add Phase 0 Excel-lock check to `/pipeline-state-cleanup`.

**F6 — Mixed tracked/gitignored files during doc reorg.** `git mv` failed on gitignored files; required splitting into `git mv` + plain `mv` batches plus path-specific `.gitignore` updates.

- **Resolved (the symptom):** completed manually.
- **Open for next pass:** `/repo-cleanup-refactor` Phase 1d should warn about mixed-track scenarios and direct to scan `.gitignore` for path-specific entries first.

**F7 — Chip-spawned WIP residue.** Both chip tasks left modified files / untracked dirs in the main checkout that required parent-session investigation.

- **Resolved (cleaned per file):** smoke-fixture chip's 220-line refactor reverted; auto-regen files committed as `e6fdca5`.
- **Captured:** `feedback_chip_task_handoff.md`.

### Low-cost — worth noting for polish

**F8 — Smoke-fixture failure side-effects accumulate.** Every failed smoke run creates: 1 orphan run dir + 1 `sweep_registry.yaml` hash sync + 1 `tools_manifest.json` regen. None auto-cleaned.

- **Captured:** `feedback_autoregen_files.md` covers the regen side; the orphan side is open as a future smoke-fixture-cleanup-robustness task.

**F9 — RED preflight for a single orphan run feels disproportionate.** System_preflight returned "Execution must halt" for a 1-run drift; the structural-vs-noise distinction collapses at the bottom severity.

- **Resolved 2026-05-23 (commit `9812cd3`):** `_check_registry()` now tiers — 1 orphan → YELLOW, ≥2 → RED. Aligns with `run_pipeline.py`'s existing "[DRIFT] auto-recovered" posture; the `_hint_for` lineage_pruner suggestion still surfaces on YELLOW so cleanup nudging is preserved.

**F10 — DRY scan gave name matches, not body matches.** `/repo-cleanup-refactor` Phase 3 surfaced "duplicate" function definitions by grep; required manual body comparison to filter out false positives.

- **Open for next pass:** `/repo-cleanup-refactor` Phase 3a should include an explicit body-comparison step in the protocol.

---

## Observations from closing-pass gates

**O1 — 17 MISS-cluster warnings** from `audit_intent_index --all`, mostly around "promote" (e.g., recent Pine document work hit `promote_strategy` as near-miss multiple times). Soft warnings; not blocking. May indicate a `pine_*` intent cluster is needed.

**O2 — 12 failures + 4 errors on `pytest tests/`** are pre-existing baseline TDs. The broader-pytest baseline check (`tools/check_broader_pytest_baseline.py`) exits 0 ("no new regressions") and the auto-section in SYSTEM_STATE.md reports "0 acknowledged failures" — scope-correct but visually confusing alongside the raw pytest output.

**O3 — broader-pytest tool prints "Resolution" footer on exit 0.** The "+ ..." lines + "Option A — fix / Option B — accept" footer look like actionable failures even when the gate passes. Cosmetic / clarity issue.

---

## Recommended skill / process tunings (for next `/skill-maintenance`)

| Skill | Tuning | Source friction |
|---|---|---|
| `/pipeline-state-cleanup` | Add Phase 0 Excel-lock check on MPS + FSP xlsx files | F5 |
| `/repo-cleanup-refactor` | Phase 0a — sibling-repo cleanliness check (uncommitted, untracked, feature branches) before any cross-repo work | F3 |
| `/repo-cleanup-refactor` | Phase 1d — explicit "scan .gitignore for path-specific entries before bulk file moves" guidance | F6 |
| `/repo-cleanup-refactor` | Phase 3a — explicit body-comparison step after grep name-match | F10 |
| `/system-health-maintenance` | §4 — acknowledge smoke fixture rot as a separate maintenance lane; don't block close on fixture failure | F2 |
| `/system-health-maintenance` | New §X — smoke fixture freshness check (manual quarterly invocation) | F2 |
| `/session-start` | Phase 1.7 — detect unstaged residue from prior session/chip; flag any unstaged file >50 LOC | F7 |
| ~~`system_preflight.py`~~ | ~~Severity tiering — single-orphan = YELLOW, not RED~~ — **landed 2026-05-23 (`9812cd3`)** | F9 |
| `tools/check_broader_pytest_baseline.py` | Suppress "Resolution" footer on exit 0 (only print on exit 1) | O3 |
| `outputs/system_reports/INTENT_INDEX.yaml` | Investigate `pine_*` cluster if MISS pattern persists across sessions | O1 |

---

## MEMORY additions landed this session

Four new feedback entries written to `C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\`:

- `feedback_cross_repo_preflight.md` (F3)
- `feedback_chip_task_handoff.md` (F7)
- `feedback_smoke_fixture_decay.md` (F2)
- `feedback_autoregen_files.md` (F8)

Plus the chip-authored `feedback_audit_checker_before_ledger.md` (F1) which landed separately as part of the chip's commit aftermath (already linked in `MEMORY.md` Build Workflow).

**Links already added to `MEMORY.md` this session:**

- Build Workflow section — `feedback_cross_repo_preflight.md`, `feedback_chip_task_handoff.md`, `feedback_smoke_fixture_decay.md` (positioned after the chip's `feedback_audit_checker_before_ledger.md` line)
- Tooling Papercuts section — `feedback_autoregen_files.md`

A future `/anthropic-skills:consolidate-memory` pass may re-organize section placement or trim duplication, but no manual indexing action is pending.

---

## What worked (preserve for next cycle)

- **Skill ordering** (state-cleanup → repo-cleanup → health) was correct.
- **Cleanup-backlog file as a checkpoint** — capture findings, then process inline once. Avoids mid-skill scope creep.
- **AskUserQuestion at every destructive / cross-repo decision point** — operator decided 9 times during the session; each decision was clear and reversible.
- **Vault snapshot at the end** (`DR_BASELINE_2026_05_22`, 979 files, engine v1.5.8) — captured the post-cleanup baseline as DR.
- **Spawning chip tasks for explicitly-deferred work** — kept the main session focused; chip's commit-message deferral notes were the critical signal back to the parent.
- **Atomic per-phase commits** — 14 commits in the session, each scoped, each passing the full 70-test pre-commit gate.

---

## Coverage check (everything surfaced is captured)

| Friction / Observation | Surface | Captured |
|---|---|---|
| F1 wrong FSP diagnosis | session | ✅ `feedback_audit_checker_before_ledger.md` |
| F2 smoke fixture rot | session | ✅ `feedback_smoke_fixture_decay.md` |
| F3 cross-repo block | session | ✅ `feedback_cross_repo_preflight.md` + backlog Item 3 |
| F4 skill Phase 1 dead ref | session | ✅ skill updated + friction-logged |
| F5 Excel lock | session | ✅ this doc + tuning queued |
| F6 mixed tracked/ignored | session | ✅ this doc + tuning queued |
| F7 chip residue | session | ✅ `feedback_chip_task_handoff.md` |
| F8 autoregen side-effects | session | ✅ `feedback_autoregen_files.md` |
| F9 RED-single-orphan | session | ✅ this doc + tuning queued |
| F10 DRY name-vs-body | session | ✅ this doc + tuning queued |
| O1 17 intent MISSes | closing | ✅ this doc |
| O2 12 baseline TDs | closing | ✅ this doc |
| O3 broader-pytest footer | closing | ✅ this doc |

13 of 13 captured. No coverage gaps remaining.
