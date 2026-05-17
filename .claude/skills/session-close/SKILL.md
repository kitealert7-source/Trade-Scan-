---
name: session-close
description: End-of-session orchestrator — Detect signals, Route conditional work, Execute fixed core + routed extras, Summarize. Authoritative conductor; delegates specialist work to /skill-maintenance, /repo-cleanup-refactor, /pipeline-state-cleanup, /system-health-maintenance, /anthropic-skills:consolidate-memory.
---

# /session-close — End-of-Session Orchestrator

Authoritative conductor for end-of-session governance. Runs in four
phases: **Detect → Route → Execute → Summarize**. Specialist skills
(`skill-maintenance`, `repo-cleanup-refactor`, `pipeline-state-cleanup`,
`system-health-maintenance`) are the implementation units; this skill
decides which run and in what order.

Design rationale for non-obvious ordering / gate choices: [`reference/design_notes.md`](./reference/design_notes.md).

---

## Phase 1 — Detect

Single-pass gathering of every signal that drives routing in Phase 2.
Run all checks; act on none yet.

```bash
# Pipeline activity this session (signal for 3.A, 3.B)
git log origin/main..HEAD --oneline 2>/dev/null | grep -E "(stage|pipeline|backtest|run_id)" | head -5

# Drift signals (signals for 3.9)
git status --short
git log origin/main..HEAD --oneline | wc -l                  # unpushed commits
wc -l MEMORY.md RESEARCH_MEMORY.md 2>/dev/null

# Day of week (signal for 3.9)
date +%A                                                      # Saturday/Sunday → weekend
```

Skills-invoked count comes from conversation memory — no shell signal.
The MPS / backtests / runs drift counts come from comparing
`TradeScan_State/` against the previous close (or visual scan if
counters aren't persisted).

Print the detection summary:

```
PHASE 1 — DETECT (<UTC>)
  Pipeline runs completed   : YES / NO     (N new run_ids)
  Skills invoked            : YES / NO     (list: <names>)
  Day of week               : <day>         (weekend = YES/NO)
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

ALWAYS:
  3.1  Commit pending tracked changes
  3.2  Document audit (manual review)
  3.3  Artifact cleanup (/tmp, root)
  3.4  Enforcement system health             [HARD: exit 2 blocks]
  3.5  Indicator registry drift              [HARD: exit 1 blocks]
  3.7  Pre-push gate (clean working tree)    [NON-NEGOTIABLE]
  3.8  Push to origin/main
  3.10 SYSTEM_STATE.md regen (FINAL)
  3.11 HEAD consistency check
  3.12 Known Issues Truthfulness Gate        [NON-NEGOTIABLE]
  3.13 Sync main checkout

CONDITIONAL (gated by Phase 1):
  3.A  Idea-gate sources refresh             ← pipeline runs = YES
  3.B  Ledger DB export                       ← pipeline runs = YES
  3.6  Skill-maintenance audit                ← skills invoked = YES
  3.9  Weekend periodic skills (8b.i + 8b.ii) ← day = weekend
```

Numeric substeps are always-on; letter substeps are conditional. The
ordering within Phase 3 interleaves them as shown above (3.1 → 3.A →
3.B → 3.2 → … → 3.13).

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

### 3.2 Document audit

Check whether any of these need updating based on today's work:

| Document | Update if... |
|---|---|
| `AGENT.md` | New invariant, lifecycle change, or pipeline stage change |
| `CLAUDE.md` | New topic that future sessions need to find |
| `RESEARCH_MEMORY.md` | New research finding (Phase 4 — max 1 entry, human approval) |
| `MEMORY.md` (`.claude/projects/`) | New gotcha, workflow, or persistent fact |
| `outputs/system_reports/` | Stale doc found during session — fix or flag |
| `.claude/skills/` | New or changed operational procedure |
| `outputs/system_reports/INTENT_INDEX.yaml` | MISS cluster revealed a real coverage gap, OR a skill under `.claude/skills/` was renamed/added/removed |
| `SYSTEM_STATE.md` `### Manual` section | **PRUNE** any entry resolved / superseded / struck-through / informational-only — see rule below |

**`SYSTEM_STATE.md ### Manual` pruning rule:** the Manual block under
`## Known Issues` is for **unresolved + operationally relevant** items
only. Resolved entries (`~~strikethrough~~`, explicit "closed by commit
...", "PASSED" status from completed phases, "now retired" /
"superseded by ...") must be REMOVED — not archived. Git preserves
history; `SYSTEM_STATE.md` is startup decision support, not historical
record. While in this step, open the file, scan `### Manual`, remove
anything that no longer affects the NEXT session's decisions. Edits
land naturally — Phase 3.10 regen preserves the Manual section.

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

### 3.6 Skill-maintenance audit [conditional: skills invoked = YES]

Run the governed audit of all SKILL.md files BEFORE the pre-push gate
so any audit commit goes through 3.7's clean-tree check.

> Invoke [`/skill-maintenance`](../skill-maintenance/SKILL.md) — produces a report;
> on `apply` lands at most one commit, on `skip` exits cleanly.

Hard findings the audit can't auto-fix (pending friction rows without
landed edits, missing reference files) require operator decision —
either resolve in the same close, or note in Phase 4 summary and defer.

Skip if a previous session-close in the same calendar day already ran it.

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

### 3.9 Weekend periodic skills [conditional: weekend = YES]

Soft prompt — does not gate session-close. If today is Sat/Sun,
consider the periodic skills below BEFORE the SYSTEM_STATE regen
(3.10) so any commits land in the closing snapshot. Why a structural
weekly reminder: [`reference/design_notes.md`](./reference/design_notes.md#39-weekend-periodic-skills--why-a-structural-reminder).

**3.9.i — Calendar-weekly (run if not done in the last 7 days):**
- `/repo-cleanup-refactor` — repo hygiene (worktrees, branches, root
  untracked, code DRY). One commit per phase.
- `/system-health-maintenance` (Phase 1 health audit only —
  `python tools/system_preflight.py`). ~5 min integrity check.

**3.9.ii — Drift-triggered (run only if a condition holds — gate on Phase 1 signals):**
- `/pipeline-state-cleanup` if ANY of:
    * MPS delta ≳ 10 new entries
    * backtests/ ≳ 20 new dirs
    * runs/ ≳ 50 new dirs
    * Stale strategy folders noticed during work
- `/anthropic-skills:consolidate-memory` if ANY of:
    * `MEMORY.md` > 40KB or > 200 lines
    * Stale facts (commit hashes that no longer exist; retired-phase refs)
    * Index entries pointing to removed topic files

If neither group applies, skip. Document in Phase 4 summary which (if any) ran.

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

# 3.6 Skill-maintenance audit (CONDITIONAL: skills invoked)
#     /skill-maintenance — produces a report; on `apply` lands at most one commit
#     that must pass the same pre-push gate (3.7) as any other work.

# 3.7 Pre-push gate — MUST be empty (excl. untracked, excl. SYSTEM_STATE.md) (NON-NEGOTIABLE)
git status --porcelain | grep -v "^??" | grep -v " SYSTEM_STATE.md$" || true

# 3.8 Push all work commits (ALWAYS)
git push origin main
git log --oneline origin/main..HEAD   # should be empty

# 3.9 Weekend periodic skills (CONDITIONAL: day = Sat/Sun)
#     3.9.i  Calendar-weekly:
#       /repo-cleanup-refactor       # repo hygiene + DRY
#       /system-health-maintenance   # Phase 1 health audit only (~5 min)
#     3.9.ii Drift-triggered (only if condition holds — see longhand):
#       /pipeline-state-cleanup      # if MPS ≳ 10 OR backtests ≳ 20 OR runs ≳ 50 OR stale folders
#       /anthropic-skills:consolidate-memory  # if MEMORY.md > 40KB / 200L OR stale facts
#     If neither group applies: skip. Document in Phase 4 summary which (if any) ran.

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
