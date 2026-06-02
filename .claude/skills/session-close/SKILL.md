---
name: session-close
description: End-of-session orchestrator — Detect signals, Route conditional work, Execute fixed core + routed extras, Summarize. Authoritative conductor; delegates specialist work to /skill-maintenance, /repo-cleanup-refactor, /pipeline-state-cleanup, /system-health-maintenance, /anthropic-skills:consolidate-memory.
---

# /session-close — End-of-Session Orchestrator

> **Design principle:** session-close optimizes for **deterministic
> transactional finalization**, NOT for **maximizing system cleanliness**.
> Maintenance accretes elsewhere; new steps must earn their slot. Before
> adding work here, ask: *if I skip this step, does the next session start
> in a degraded state?* If no → it belongs in Deferred Maintenance, not here.

Authoritative conductor for end-of-session governance. Runs in four
phases: **Detect → Route → Execute → Summarize**. Specialist skills
(`skill-maintenance`, `repo-cleanup-refactor`, `pipeline-state-cleanup`,
`system-health-maintenance`) are the implementation units; this skill
decides which run and in what order.

Phase 3 splits into two blocks:
- **CORE** — always runs; hard transactional + integrity gates
- **EPILOGUE** — conditional; only fires when its signal is present

Design rationale for non-obvious ordering / gate choices: [`reference/design_notes.md`](./reference/design_notes.md).
Step taxonomy (CORE vs EPILOGUE vs Deferred Maintenance): [`reference/design_notes.md#step-taxonomy`](./reference/design_notes.md#step-taxonomy).

---

## Phase 1 — Detect

Single-pass gathering of every signal that drives routing in Phase 2.
Run all checks; act on none yet.

```bash
# Pipeline activity this session (signal for 3.A, 3.B)
git log origin/main..HEAD --oneline 2>/dev/null | grep -E "(stage|pipeline|backtest|run_id)" | head -5

# Skill-doctrine modifications this session (narrow signal for 3.6)
git diff --name-only origin/main..HEAD 2>/dev/null | grep -E "^\.claude/skills/.+/SKILL\.md$"

# Drift signals (signals for 3.9 Deferred Maintenance)
git status --short
git log origin/main..HEAD --oneline | wc -l                  # unpushed commits
wc -l MEMORY.md RESEARCH_MEMORY.md 2>/dev/null

# Day of week (informational; no longer auto-fires weekly skills)
date +%A
```

Skill-doctrine signal for 3.6 is the **narrow** trigger: only fires when
this session's commits actually modified one or more `SKILL.md` files.
Skills being *invoked* during the session does NOT trigger 3.6 — invoking
`/format-excel-ledgers` ten times doesn't change skill doctrine, so it
shouldn't fire a 20-skill audit. The MPS / backtests / runs drift counts
come from comparing `TradeScan_State/` against the previous close (or
visual scan if counters aren't persisted).

Print the detection summary:

```
PHASE 1 — DETECT (<UTC>)
  Pipeline runs completed   : YES / NO     (N new run_ids)
  SKILL.md modified         : YES / NO     (list: <slugs>)        ← signal for 3.6
  Skills invoked            : YES / NO     (list: <names>; informational only)
  Day of week               : <day>         (informational; weekend prompts in 3.9 backlog)
  Drift signals:
    MPS delta               : N             (threshold ≥10 → trigger /pipeline-state-cleanup)
    backtests/ new dirs     : N             (threshold ≥20 → trigger /pipeline-state-cleanup)
    runs/ new dirs          : N             (threshold ≥50 → trigger /pipeline-state-cleanup)
    MEMORY.md               : N lines / K KB (threshold >200L or >40KB → /anthropic-skills:consolidate-memory)
    RESEARCH_MEMORY.md      : N lines / K KB (threshold >600L or >40KB → compact_research_memory.py)
  Tracked changes pending   : YES / NO     (N files)
  Unpushed commits          : N
```

---

## Phase 2 — Route

Given Phase 1, declare the execution plan. Print BEFORE Phase 3 so
the operator sees the full sequence at a glance and can challenge it
before anything runs.

```
PHASE 2 — ROUTE

CORE — always runs (HARD-TXN + HARD-GATE):
  3.1  Commit pending tracked changes        [HARD-TXN]
  3.4  Enforcement system health             [HARD-GATE: exit 2 blocks]
  3.5  Indicator registry drift              [HARD-GATE: exit 1 blocks]
  3.7  Pre-push gate (clean working tree)    [HARD-TXN: NON-NEGOTIABLE]
  3.8  Push to origin/main                   [HARD-TXN]
  3.12 Known Issues Truthfulness Gate        [HARD-GATE: NON-NEGOTIABLE]
  3.10 SYSTEM_STATE.md regen (FINAL)         [HARD-TXN]
  3.11 HEAD consistency check                [HARD-TXN]
  3.13 Sync main checkout (worktree path)    [HARD-TXN if worktree]

EPILOGUE — conditional (signal-gated):
  3.A  Idea-gate sources refresh             ← pipeline runs = YES
  3.B  Ledger DB export                       ← pipeline runs = YES
  3.6  Skill-maintenance audit                ← SKILL.md modified in session commits
  3.9  Deferred Maintenance emission          ← always (writes Deferred Maintenance section)
  3.C  Active Charter sync                    ← charter heading present in SYSTEM_STATE
  3.3  Artifact cleanup (/tmp, root)          ← legacy; partial overlap with /repo-cleanup-refactor (Change D eligible)
```

**CORE failure blocks close.** EPILOGUE skips emit `[SKIP] reason: <signal>` and do not block.

Numeric substeps are always-on; letter substeps are conditional. The
ordering within Phase 3 interleaves them as shown above (3.1 → 3.A →
3.B → … → 3.13).

> **Routing is not negotiable mid-execution.** If a Phase 3 step
> uncovers a NEW reason to add work (e.g., commit reveals a stale
> file), record it in the Phase 4 summary and address it next session
> — do not loop back to re-route.

---

## Phase 3 — Execute

The fixed-order execution. Conditional substeps either run or print
`[SKIP] reason: <signal>` per the Phase 2 plan.

### 3.1 Commit pending tracked changes

```bash
git status
git diff --stat
```

- Stage and commit all meaningful changes (group logically — don't lump everything)
- Follow repo commit style: summary line + detail body + `Co-Authored-By` trailer
- Do NOT commit secrets, .env, or credentials
- **Tracked deletions MUST be committed or restored** — never left unstaged
- **Do NOT regenerate or commit `SYSTEM_STATE.md` here** — that is 3.10

| File type | Action |
|---|---|
| Tracked changes | MUST commit or revert |
| Tracked deletions | MUST commit or restore |
| Ignored files (.gitignore) | Ignore — no action needed |
| Untracked files (new, not yet staged) | OK to leave |

### 3.A Refresh idea-gate sources [conditional: pipeline runs = YES]

Regenerate the data sources that feed the Idea Evaluation Gate
(Stage -0.20). These are append-only / regenerated artifacts —
safe to overwrite.

```bash
python tools/generate_run_summary.py            # run_summary.csv
python tools/backfill_hypothesis_log.py         # hypothesis_log.json (idempotent)
python -m tools.research_memory_append          # only AFTER human approves candidate entry
python tools/generate_guard_manifest.py         # tools_manifest.json (if any tools/*.py changed)
```

| Source | Regenerated by | Notes |
|---|---|---|
| `run_summary.csv` | `generate_run_summary.py` | Joins run_registry + index.csv + MPS |
| `hypothesis_log.json` | `backfill_hypothesis_log.py` | Idempotent — skips existing entries |
| `run_registry.json` | Auto-updated by pipeline | No manual action |
| `RESEARCH_MEMORY.md` | `research_memory_append` (Phase 4) | Max 1 entry per session, human approval required |
| `tools_manifest.json` | `generate_guard_manifest.py` | SHA-256 guard manifest — regen if any `tools/*.py` changed |

- Use `--dry-run` on backfill if unsure what will change
- RESEARCH_MEMORY: generate candidate from index.csv analysis, present to human, append only after "yes"
- If RESEARCH_MEMORY exceeds 600 lines / 40 KB: `python tools/compact_research_memory.py --dry-run` then `--apply`
- Stage all regenerated files and include in the session-close commit

### 3.B Ledger DB export [conditional: pipeline runs = YES]

Regenerate Excel exports from the authoritative SQLite ledger so
Excel files stay in sync.

```bash
python tools/ledger_db.py --export
```

- Regenerates `Strategy_Master_Filter.xlsx` and `Master_Portfolio_Sheet.xlsx`
- Safe anytime — reads from DB, overwrites Excel
- Use `--stats` to verify row counts before export

### 3.3 Artifact cleanup

- Delete any `/tmp/` scratch scripts created during the session
- Check for orphaned files in repo root (Invariant 25: no transient scripts in root)
- If pipeline ran: verify `TradeScan_State/` artifacts are consistent

### 3.4 Enforcement system health [HARD: exit 2 blocks]

Verify the intent-routing + violation-detection hook system is not
in a degraded state. Runs structural, overlap, dead-intent,
misclassification, violation, and MISS-cluster checks.

```bash
python tools/audit_intent_index.py --all
```

| Exit | Meaning | Action |
|---|---|---|
| `0` | Clean | Proceed |
| `1` | Warnings | Note categories in Phase 4 summary (dead intents, MISS clusters, misclassifications, tool_before_skill breaches). Do NOT attempt to fix mid-close. |
| `2` | Hard errors | **Block session close.** A HARD intent has a broken regex, missing skill file, duplicate id, or a hook fails to compile. Enforcement is degraded — fix `outputs/system_reports/INTENT_INDEX.yaml` or the failing hook before continuing. |

Also review:

- `.claude/logs/violations.jsonl` — scan for `hard_violation` events
  this session. Repeated violations on the same intent mean the
  routing message is being bypassed; tighten the rule or the skill doc.
- MISS clusters from audit output — if a real coverage gap appears
  (same n-gram across multiple MISSes, or a HIGH-RISK single MISS),
  extend `INTENT_INDEX.yaml` before close. Keep `MAX_INTENTS = 25` in mind.

### 3.5 Indicator registry drift [HARD: exit 1 blocks]

Verify `indicators/INDICATOR_REGISTRY.yaml` has not drifted from the
`indicators/` directory tree. Why a defence layer despite the
pre-commit hook: [`reference/design_notes.md`](./reference/design_notes.md#35-indicator-registry-drift--why-a-defence-layer).

```bash
python tools/indicator_registry_sync.py --check
```

| Exit | Meaning | Action |
|---|---|---|
| `0` | Disk ↔ registry in sync | Proceed |
| `1` | Drift detected | **Block session close.** Either: (a) `python tools/indicator_registry_sync.py --add-stubs` then `git add indicators/INDICATOR_REGISTRY.yaml` and commit, OR (b) restore the missing `.py` files / remove the orphan registry entries. Re-run `--check` until it exits 0. |

### 3.6 Skill-maintenance audit [conditional: SKILL.md modified this session]

Run the governed audit of all SKILL.md files BEFORE the pre-push gate
so any audit commit goes through 3.7's clean-tree check.

**Trigger:** any `SKILL.md` file appears in
`git diff --name-only origin/main..HEAD` for this session — i.e., this
session's commits actually modified skill doctrine. Skills being
*invoked* during the session does NOT fire this audit; invoking a skill
doesn't change its `SKILL.md` content, so a 20-skill format audit is
wasted work. Narrowed from "skills invoked = YES" to "SKILL.md
modified" on 2026-05-25 to remove the trigger over-firing.

Fallback paths (still fire even without SKILL.md modification):
- **Manual demand:** operator explicitly invokes `/skill-maintenance`
- **Once-monthly cadence:** if `outputs/.session_state/last_skill_audit.txt`
  is older than 30 days, auto-fire as a slow-creep catch

> Invoke [`/skill-maintenance`](../skill-maintenance/SKILL.md) — produces a report;
> on `apply` lands at most one commit, on `skip` exits cleanly.

Hard findings the audit can't auto-fix (pending friction rows without
landed edits, missing reference files) require operator decision —
either resolve in the same close, or note in Phase 4 summary and defer.

### 3.7 Pre-push gate — strict clean working tree [NON-NEGOTIABLE]

```bash
git status --porcelain | grep -v "^??" || true
```

**This MUST return empty output** (except for `SYSTEM_STATE.md`, which
is regenerated in 3.10 and intentionally not touched yet).

- Any tracked file that is modified or deleted and not committed = **ERROR**
- Do NOT label dirty state as "intentional" or "pre-existing"
- Do NOT end the session if this check fails — go back and commit or revert

If non-empty (aside from `SYSTEM_STATE.md`):
```
ERROR: Dirty working tree — tracked changes detected. Commit or revert before closing.
```

### 3.8 Push to origin/main

```bash
git log --oneline origin/main..HEAD   # review what's about to go out
git push origin main
```

All work commits MUST be pushed BEFORE the SYSTEM_STATE snapshot is
taken, so the snapshot's "unpushed count" reflects reality (0).

### 3.9 Deferred Maintenance emission [always; emits to SYSTEM_STATE]

Replaces the previous "execute weekend periodic skills inline" model.
**No skills are invoked at session-close.** Instead, drift signals are
emitted as entries in the `## Deferred Maintenance` section of
SYSTEM_STATE.md by `tools/system_introspection.py` (which runs at
3.10). The operator addresses entries manually next session — or now
if they choose — by invoking the relevant cleanup skill directly.

**Why this changed (2026-05-25):** auto-firing 4 cleanup skills at
session-close inflated wall-clock by 10-30 min and confused the
transactional/maintenance boundary. The new model treats session-close
as transactional finalization only; maintenance is surfaced for
operator awareness, not executed. See the design principle at the top
of this file and the step taxonomy in
[`reference/design_notes.md#step-taxonomy`](./reference/design_notes.md#step-taxonomy).

**Semantic distinction (NON-NEGOTIABLE):** the section is named
`## Deferred Maintenance` — explicitly distinct from `## Known Issues`.
Future operators reading SYSTEM_STATE.md must NOT psychologically
conflate these entries with unresolved problems. Each entry carries a
`[CATEGORY]` prefix (`[SIZE]`, `[CALENDAR]`, `[DRIFT]`, `[PERIODIC]`)
that reinforces it is a *deferral decision*, not a fire.

**Auto-detected signals (emitted by `collect_deferred_maintenance`):**
| Category | Threshold | Suggested action |
|---|---|---|
| `[SIZE]` | RESEARCH_MEMORY.md ≥ 32 KB or ≥ 500 lines | `python tools/compact_research_memory.py --dry-run` |
| `[CALENDAR]` | Sat/Sun | `/repo-cleanup-refactor` + `/system-health-maintenance` Phase 1 |
| `[DRIFT]` (future) | MPS Δ ≥ 10, backtests/ Δ ≥ 20, runs/ Δ ≥ 50 | `/pipeline-state-cleanup` (needs sidecar; not yet implemented) |
| `[PERIODIC]` (future) | Last `/repo-cleanup-refactor` > 14 days ago | `/repo-cleanup-refactor` (needs git-log scan; not yet implemented) |

**Manual section:** `### Manual (operator-deferred items)` under
`## Deferred Maintenance` persists across regen. Use it for deferrals
that lack an auto-signal (e.g., "deferred performance test until
post-Phase-7b"). Entries here are NOT problems; they are tracked
opportunities.

**Cap:** auto-detected entries capped at 5 (top by signal strength).
The Manual section is uncapped.

No action required at 3.9 itself — the emission happens during 3.10.
This step exists in the routing table for visibility only.

### 3.C Active Charter sync [conditional: charter exists]

If `SYSTEM_STATE.md` contains a `#### Active Charter — ` heading inside `### Manual`, append today's contribution before the closing snapshot regen at 3.10. The regen at 3.10 preserves the Manual block verbatim (see [`tools/system_introspection.py:_preserve_manual_section`](../../../tools/system_introspection.py)), so the edit rides along in the closing snapshot commit — no separate commit needed.

1. Detect:
   ```bash
   grep -n "^#### Active Charter — " SYSTEM_STATE.md
   ```
   No match → skip this step entirely.

2. Prompt the operator (single free-text prompt):
   > "Did this session advance the active charter? One-line summary
   > (≤120 chars), Enter to skip, or type `manual` to pivot/supersede/park."

3. Branch on the response:
   - **Empty (Enter):** no edit, no log entry. Charter remains as-is.
   - **`manual`:** halt this step and instruct the operator:
     > "Charter pivots stay human-authored. Open `SYSTEM_STATE.md`, demote
     > the current `#### Active Charter` block to a regular bulleted dated
     > entry below, then (optionally) write a new
     > `#### Active Charter — <today> — <new-slug>` block at the top of
     > the Manual section. Re-run /session-close once the file is saved."
   - **Anything else (the summary):** edit `SYSTEM_STATE.md` to log the contribution under the charter's `**Sessions on this charter:**` list.
     - Format: `  - YYYY-MM-DD: <summary>`
     - If the only existing entry is the `(none yet — ...)` placeholder, **REPLACE** it with the new entry. Otherwise **APPEND** below the last existing entry.

4. Do not commit separately. The edit will be captured in 3.10's `session: closing SYSTEM_STATE snapshot` commit because the regen preserves the Manual block.

### 3.10 Regenerate SYSTEM_STATE.md — FINAL [ALWAYS]

```bash
python tools/system_introspection.py
```

- Runs AFTER 3.8's push so the snapshot reports `0 unpushed` and the
  true end-of-session state.
- Review output — `SESSION STATUS` should be `OK` (or `WARNING` with
  clearly-documented runtime reasons).
- Commit + push the snapshot as the closing entry:

```bash
git add SYSTEM_STATE.md
git commit -m "session: closing SYSTEM_STATE snapshot"
git push origin main
```

The committed snapshot is the historical record of session end state —
the next session's first read reflects what was true at close.

In-flight pipeline activity caveat (when other tracked files mutate
between 3.7 and 3.10): see
[`reference/design_notes.md`](./reference/design_notes.md#310-in-flight-activity-during-close).

### 3.11 HEAD consistency check

Right after the snapshot regen and BEFORE committing it:

```bash
echo "Snapshot HEAD ref:"
grep -E "^- Last substantive commit:" SYSTEM_STATE.md | head -1
echo "Actual HEAD     :"
git rev-parse --short HEAD
```

These two values MUST match. If they differ, `system_introspection.py`
captured `git log -1` BEFORE you ran it (a pipeline tool snuck a
commit in between 3.8 push and 3.10 regen, OR you regenerated before
3.8's push completed). Re-run the regen to converge.

Note: AFTER the closing commit lands, the snapshot's `Last
substantive commit:` line references the commit BEFORE itself — this
permanent off-by-one is expected and acceptable; see
[`reference/design_notes.md`](./reference/design_notes.md#311-head-consistency--the-permanent-off-by-one).

### 3.12 Known Issues Truthfulness Gate [NON-NEGOTIABLE]

Defensive gate that catches stale `SYSTEM_STATE.md` snapshots, silent
auto-populator failures, and new pytest regressions vs the
acknowledged baseline. Design rationale + auto-vs-manual section
distinction: [`reference/known_issues_gate.md`](./reference/known_issues_gate.md).

```bash
# Step A — broader-pytest baseline gate (catches NEW regressions vs
# outputs/.session_state/broader_pytest_baseline.json).
#   Exit 0 -> baseline match or improvement
#   Exit 1 -> NEW failure(s) -> BLOCK close
#   Exit 2 -> internal pytest error
python tools/check_broader_pytest_baseline.py
BP_EXIT=$?
if [ "$BP_EXIT" -eq 1 ]; then
    echo "ERROR: broader-pytest regression detected. Either fix the new"
    echo "       failure(s) or explicitly accept by updating the baseline:"
    echo "  python tools/check_broader_pytest_baseline.py --update-baseline \\"
    echo "       --rationale '<why these are accepted>'"
    exit 1
fi

# Step A2 — directive-provenance gate (enforces the directive co-location rule:
# every run/strategy whose source directive is RECOVERABLE must carry
# directive.txt; grandfathers genuine pre-preservation losses via its baseline).
#   Exit 0 -> clean (or only new acknowledged-unrecoverable losses)
#   Exit 1 -> a recoverable directive is NOT co-located (rule bypassed) -> BLOCK
python tools/verify_directive_provenance.py
DP_EXIT=$?
if [ "$DP_EXIT" -eq 1 ]; then
    echo "ERROR: a run/strategy is missing its (recoverable) source directive."
    echo "       Backfill it, or acknowledge new genuine losses:"
    echo "  python tools/backfill_run_directives.py --target <runs|strategies> --apply"
    echo "  python tools/verify_directive_provenance.py --update-baseline --rationale '<why>'"
    exit 1
fi

# Step B — Re-derive gate-suite signals (5-file fast roster from
# system_introspection's _GATE_TEST_SUITE; broader-pytest is Step A,
# not here) + confirm the auto-populator surfaced them.
TEST_FAILS=$(python -m pytest tests/ -q 2>&1 | grep -oE "[0-9]+ failed" | head -1 | grep -oE "[0-9]+" || echo 0)
SKIPPED=$(python -m pytest tests/ -q 2>&1 | grep -oE "[0-9]+ skipped" | head -1 | grep -oE "[0-9]+" || echo 0)
HAS_AUTO_SECTION=$(grep -c "^### Auto-detected" SYSTEM_STATE.md || echo 0)
HAS_BLOCKERS=$([ "$TEST_FAILS" -gt 0 ] && echo 1 || echo 0)

echo "test failures      : $TEST_FAILS"
echo "skipped tests      : $SKIPPED"
echo "Auto section exists: $HAS_AUTO_SECTION  (expected 1 when blockers > 0)"
```

**Block session close if** `HAS_BLOCKERS == 1` AND `HAS_AUTO_SECTION == 0`
(auto-populator should have surfaced something but didn't — silent
failure / stale snapshot):

```
ERROR: blockers detected but SYSTEM_STATE.md has no Auto-detected
section. Re-run system_introspection.py and confirm the blockers
appear under "### Auto-detected" before closing.
  - test failures: <N>
```

For deferred items the automation can't see, edit `### Manual` directly — the `### Auto-detected` section regenerates each run and will clobber edits there; `### Manual` persists across regen.

### 3.13 Sync main checkout

After the closing snapshot lands on origin/main, fast-forward the
main checkout's working tree so its `SYSTEM_STATE.md` reflects the
new closing snapshot.

```bash
case "$(git rev-parse --absolute-git-dir 2>/dev/null)" in
  */worktrees/*)
    MAIN_REPO=$(git worktree list --porcelain | awk '$1=="worktree"{print $2; exit}')
    git -C "$MAIN_REPO" pull --ff-only \
      || echo "[warn] main checkout FF failed (dirty, non-main branch, or diverged) — sync manually"
    ;;
esac
```

The `*/worktrees/*` guard fires only from a git worktree; from the
main checkout the case falls through and the close finishes silently.
Best-effort beyond that — the close has already succeeded; if the
main checkout is dirty or on a non-main branch, the warning surfaces
the issue without blocking.

---

## Phase 4 — Summarize

Echo the Phase 1 detection, Phase 2 routing, and Phase 3 outcomes into
a structured close summary for the next session's first read.

```
PHASE 4 — SUMMARY (<UTC>)

  Closed by    : <agent/operator>
  Commit       : <SHA>  (closing snapshot)
  Hard gates   : N passed / 0 blocked

  Conditional substeps:
    [RAN/SKIP] 3.A  Idea-gate refresh
    [RAN/SKIP] 3.B  Ledger DB export
    [RAN/SKIP] 3.6  Skill-maintenance audit
    [RAN/SKIP] 3.9  Weekend periodic skills (list which subskills ran)

  Significant changes this session:
    <1-3 bullets>

  Pending for next session:
    <list or "none">
```

The summary becomes input for the next session's Phase 1 baseline.

---

## Quick Version (Copy-Paste, phase-ordered)

```bash
# === PHASE 1 — DETECT ===
git status --short
git log origin/main..HEAD --oneline | wc -l
wc -l MEMORY.md RESEARCH_MEMORY.md 2>/dev/null
date +%A
# (record: pipeline_runs?, skills_invoked?, weekend?, drift?)

# === PHASE 2 — ROUTE (declare plan, then execute Phase 3 in order below) ===

# === PHASE 3 — EXECUTE ===

# 3.1 Commit pending tracked changes (ALWAYS — NOT SYSTEM_STATE.md)
git status
git add <files>
git commit -m "message"

# 3.A Idea-gate refresh (CONDITIONAL: pipeline runs)
python tools/generate_run_summary.py
python tools/backfill_hypothesis_log.py
python -m tools.research_memory_append        # only after human approves candidate
python tools/generate_guard_manifest.py       # only if tools/*.py changed
git add ../TradeScan_State/research/run_summary.csv ../TradeScan_State/hypothesis_log.json RESEARCH_MEMORY.md tools/tools_manifest.json
git commit -m "session: idea gate refresh"

# 3.B Ledger DB export (CONDITIONAL: pipeline runs)
python tools/ledger_db.py --export

# 3.4 Enforcement system health — exit 2 blocks, exit 1 note warnings (ALWAYS)
python tools/audit_intent_index.py --all

# 3.5 Indicator registry drift — exit 1 blocks (ALWAYS)
python tools/indicator_registry_sync.py --check

# 3.6 Skill-maintenance audit (CONDITIONAL: SKILL.md modified in session commits)
#     git diff --name-only origin/main..HEAD | grep -E "\.claude/skills/.+/SKILL\.md$"
#     /skill-maintenance — produces a report; on `apply` lands at most one commit
#     that must pass the same pre-push gate (3.7) as any other work.
#     Fallback: monthly cadence + manual demand still fire even without SKILL.md mods.

# 3.7 Pre-push gate — MUST be empty (excl. untracked, excl. SYSTEM_STATE.md) (NON-NEGOTIABLE)
git status --porcelain | grep -v "^??" | grep -v " SYSTEM_STATE.md$" || true

# 3.8 Push all work commits (ALWAYS)
git push origin main
git log --oneline origin/main..HEAD   # should be empty

# 3.9 Deferred Maintenance emission (ALWAYS — no skills invoked at close)
#     Drift signals are emitted as entries in SYSTEM_STATE.md
#     ## Deferred Maintenance section by tools/system_introspection.py
#     (which runs at 3.10). Operator addresses them manually next session
#     by invoking /repo-cleanup-refactor, /pipeline-state-cleanup, etc.
#     directly. No execution at close.
#     Semantic: ## Deferred Maintenance is DISTINCT from ## Known Issues
#     — entries are deferral decisions, NOT problems. Each carries a
#     [CATEGORY] prefix ([SIZE], [CALENDAR], [DRIFT], [PERIODIC]).

# 3.C Active Charter sync (CONDITIONAL: charter exists in SYSTEM_STATE.md ### Manual)
#     If `#### Active Charter — ` heading present, prompt operator for one-line
#     summary (Enter = skip, `manual` = pivot/supersede/park). Edit "Sessions on
#     this charter:" list in place; 3.10 regen preserves the Manual block.
grep -n "^#### Active Charter — " SYSTEM_STATE.md || true

# 3.12 Broader-pytest baseline — exit 1 blocks close (NEW failure since baseline) (NON-NEGOTIABLE)
#      Auto-populator only checks the gate suite; this catches broader regressions.
python tools/check_broader_pytest_baseline.py

# 3.10 + 3.11 + 3.12 + Closing commit (ALWAYS)
python tools/system_introspection.py
# (verify HEAD consistency before committing — Snapshot HEAD ref ≡ git rev-parse --short HEAD)
git add SYSTEM_STATE.md
git commit -m "session: closing SYSTEM_STATE snapshot"
git push origin main
git status --porcelain | grep -v "^??" || true   # must be empty

# 3.13 Sync main checkout (worktree-only) (ALWAYS)
case "$(git rev-parse --absolute-git-dir 2>/dev/null)" in
  */worktrees/*)
    MAIN_REPO=$(git worktree list --porcelain | awk '$1=="worktree"{print $2; exit}')
    git -C "$MAIN_REPO" pull --ff-only || true
    ;;
esac

# === PHASE 4 — SUMMARIZE ===
# Print the structured summary (see longhand Phase 4 template).
```

---

## When to Skip

- Trivial read-only session (no changes made) — skip all
- Mid-task pause (resuming same session) — skip push, do commit

## Anti-Patterns

- Ending with "I'll push later" — you won't
- Committing everything as one giant commit — group logically
- Regenerating `SYSTEM_STATE.md` BEFORE the main push — the snapshot then
  bakes in a misleading "BROKEN: N unpushed" line that misrepresents
  the session's end state to the next session
- Skipping doc updates — causes stale docs that mislead future sessions
- Pushing without reviewing `git diff` — catches accidental includes
- Labelling tracked deletions or modifications as "intentional unstaged" — never acceptable
- Leaving `.claude/skills/` or any tracked directory in a deleted-but-uncommitted state
- Ending with broken hard intents, an unread `violations.jsonl`, or a failing `audit_intent_index.py --all` — silent enforcement rot
- Re-routing mid-Phase-3 because a new issue surfaced — record it for next session, don't loop

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| 2026-05-17 | `grep -v "^??"` exits 1 on no match, aborts `&&` chains | wrapped grep with `\|\| true` in §3.7 + Quick Version |
