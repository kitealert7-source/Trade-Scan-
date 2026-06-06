---
name: session-start
description: Session preparation — reads SYSTEM_STATE (incl. Active Charter), RESEARCH_MEMORY, git log, and pending directives to surface the active research charter and the top 3 infra + top 3 research priorities. Read-only; no commits, no pipeline runs.
---

# session-start

**Purpose:** arrive at a concrete 6-task priority list in under 2 minutes — start on signal, not on memory recall.

---

## Phase 1 — Collect state signals

Run all reads before synthesizing. Each is < 5 s.

### 1.1 System preflight

// turbo
```bash
python tools/system_preflight.py 2>&1 | tail -8
```
Extract: `SESSION STATUS` line, any `WARN` or `ERROR` lines.

### 1.2 Recent git activity

// turbo
```bash
git log --oneline -10 && echo "---" && git status --short
```
Extract: date of last session-close commit, any uncommitted changes.

### 1.3 Known issues + Active Charter

Read `SYSTEM_STATE.md` — extract:
- The `SESSION STATUS` banner (first ~10 lines)
- The full `### Manual` block under `## Known Issues`
- **Active Charter (if present):** locate the `#### Active Charter — ` heading inside `### Manual`. If found, extract:
  - **Slug** (the trailing `<yyyy-mm-dd> — <short-slug>` portion of the heading)
  - **Focus** (the paragraph under `**Focus:**`) — first sentence is enough for the brief
  - **Last session entry** (the last bullet under `**Sessions on this charter:**`) — used for staleness check
  - **Stale flag:** if the latest session date is >14 days behind today (or the only entry is the `(none yet — ...)` placeholder >14 days old), mark the charter STALE.

### 1.4 Research pulse

Read `RESEARCH_MEMORY.md` — scan for:
- Lines starting with `**NEXT:**` or `NEXT:` → active continuation points
- Arcs labeled `IN_PROGRESS`, `OPEN`, or carrying an open hypothesis

### 1.5 Pending directives

// turbo
```bash
ls directives/inbox/ directives/active/ 2>/dev/null || echo "(both empty)"
```
`inbox/` → ready to run. `active/` → may be mid-pipeline; confirm state.

### 1.6 File-size warnings

// turbo
```bash
python -c "
import os, re
from pathlib import Path
# RESEARCH_MEMORY.md lives at repo root.
rm = sum(1 for _ in open('RESEARCH_MEMORY.md', encoding='utf-8'))
rk = os.path.getsize('RESEARCH_MEMORY.md') // 1024
print(f'RESEARCH_MEMORY.md: {rm} lines / {rk} KB  (limit 40 KB)')
# MEMORY.md is the AUTO-MEMORY file under ~/.claude/projects/<slug>/memory/ (NOT repo root).
# CC derives <slug> by replacing each non-alphanumeric char of the project path with '-'.
slug = re.sub(r'[^A-Za-z0-9]', '-', str(Path.cwd()))
mem = Path.home() / '.claude' / 'projects' / slug / 'memory' / 'MEMORY.md'
if not mem.exists():
    hits = list((Path.home() / '.claude' / 'projects').glob('*/memory/MEMORY.md'))
    mem = hits[0] if len(hits) == 1 else None
if mem and mem.exists():
    m = sum(1 for _ in open(mem, encoding='utf-8'))
    print(f'MEMORY.md (auto):   {m} lines  (limit 200)')
else:
    print('MEMORY.md (auto):   not found - check ~/.claude/projects/<slug>/memory/')
"
```

---

## Phase 2 — Synthesize priorities

Apply the triage tables below. Pick the top 3 from each side. Skip tiers with no signal.

### Infra triage

| Tier | Signal | Source | Action |
|---|---|---|---|
| BLOCKER | SESSION STATUS = BROKEN | SYSTEM_STATE.md | Fix before any research |
| BLOCKER | Uncommitted changes + no recent close | git status | Stash or commit before proceeding |
| ACTION | Items in `### Manual` known issues | SYSTEM_STATE.md | Address each open item |
| ACTION | Test failures in `### Auto-detected` | SYSTEM_STATE.md | Investigate + fix |
| ACTION | MEMORY.md ≥ 200 lines | 1.6 | `/anthropic-skills:consolidate-memory` |
| ACTION | RESEARCH_MEMORY.md ≥ 40 KB | 1.6 | `python tools/compact_research_memory.py --dry-run` then `--apply` |
| WATCH | SESSION STATUS = WARNING | SYSTEM_STATE.md | Decide if it blocks research |
| WATCH | Intent-index warnings (dead / misclassified) | last audit output | `python tools/audit_intent_index.py --all` |
| WATCH | Directives lingering in `active/` from prior session | 1.5 | Confirm state or `python tools/reset_directive.py <ID>` |

### Research triage

| Tier | Signal | Source | Action |
|---|---|---|---|
| RESUME | `NEXT:` lines in RESEARCH_MEMORY.md | 1.4 | Pick up the active arc |
| RESUME | Directives in `inbox/` ready to run | 1.5 | `/execute-directives` |
| OPEN | Open hypothesis arcs | 1.4 | `/hypothesis-testing` or `/basket-hypothesis-testing` |
| OPEN | "pending" items in MEMORY.md | MEMORY.md | Per-item action |
| PENDING | Portfolio composition gaps | MEMORY.md | `/portfolio-research` then `/portfolio-selection-add` |
| PENDING | Deferred from last session-close Phase 4 | git log -1 | Pick up noted continuation |

---

## Phase 3 — Emit session brief

Output to terminal only. No file writes.

```
=== SESSION START BRIEF — <YYYY-MM-DD> ===

System : <OK | WARNING | BROKEN>
Branch : <current-branch>  (<N commits ahead/behind origin/main>)
Last close : <date + short-hash of last session-close commit>

── ACTIVE CHARTER (emit only if present in SYSTEM_STATE.md) ──
  <slug>  [last update: <yyyy-mm-dd> — <FRESH | STALE (>14d)>]
  Focus: <first sentence of the Focus paragraph>

── INFRA PRIORITIES (top 3) ────────────────────────────
1. [<BLOCKER|ACTION|WATCH>] <description>  →  <action or command>
2. [<tier>] <description>  →  <action or command>
3. [<tier>] <description>  →  <action or command>

── RESEARCH PRIORITIES (top 3) ─────────────────────────
1. [<RESUME|OPEN|PENDING>] <description>  →  <action or directive ID>
2. [<tier>] <description>  →  <action or directive ID>
3. [<tier>] <description>  →  <action or directive ID>

── MAINTENANCE REMINDERS (emit only if triggered) ──────
  • MEMORY.md <N> lines  →  consolidate before next session-close
  • RESEARCH_MEMORY.md <N> KB  →  compact_research_memory.py before infra work
  • Active Charter STALE (>14d)  →  update sessions log or supersede
  • Weekend  →  /repo-cleanup-refactor and /pipeline-state-cleanup eligible

=========================================================
Suggested first task: <Infra #1 if BLOCKER; else Active Charter focus if present and FRESH; else Research #1>
```

---

## Constraints

- **Read-only.** No file mutations, no commits, no pipeline runs, no directive admission.
- **Fast.** Full skill in under 2 minutes. If a read is slow, skip it and note the omission.
- **Honest about gaps.** No `NEXT:` entries → say so; do not invent tasks.
- **BROKEN is always Infra #1.** If SESSION STATUS = BROKEN, surface it first and recommend pausing research until resolved.

---

## When to invoke

- Start of every non-trivial working session.
- After a multi-day absence.
- Mid-session when context is lost and you need re-orientation.

## When NOT to invoke

- Already have working session context — no need to re-orient.
- Trivial read-only / question-answering sessions with no file work.

---

## Related skills

| Skill | Relationship |
|---|---|
| `/session-close` | Sibling pair — generates the state this skill reads; invoke at session end |
| `/session-retro` | Pre-close sibling — stages the HIGH ROI pick + MONITOR watch-list (in SYSTEM_STATE Deferred Maintenance) that inform the next session |
| `/system-health-maintenance` | Deeper audit if SESSION STATUS = BROKEN |
| `/skill-maintenance` | If friction entries need attention (weekend cadence) |
| `/repo-cleanup-refactor` | If infra debt surfaces in priorities (weekend cadence) |

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
