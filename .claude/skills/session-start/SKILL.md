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

Regenerate the snapshot first so nothing stale is read downstream (this one write is authorized infrastructure maintenance, not a research mutation):

// turbo
```bash
python tools/system_introspection.py && python tools/system_preflight.py 2>&1 | tail -8
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
The line count above is a soft proxy — the binding cap is **bytes** (the index loads in full
only under ~24.4 KB). For the authoritative status (the same gate `/session-close` §3.14 enforces):

// turbo
```bash
python tools/check_memory_index_budget.py
```

### 1.7 Vault nav-layer freshness (advisory)

// turbo
```bash
if [ -f ../TS_Obsidian_Vault/system/_sync.py ]; then
  python ../TS_Obsidian_Vault/system/_sync.py --summary
else
  echo "(vault nav layer absent - skipped)"
fi
```
Read line 1's first token: `PASS` (nothing to do) or `WATCH` (the named vault maps need review).
Advisory only — the vault is a subordinate map layer (Invariant #31), never a blocker. The `[ -f ]`
guard also no-ops cleanly from a worktree (where `../` does not resolve to the container folder).

### 1.8 Repo + working-tree state (LIVE — catch drift since last close)

// turbo
```bash
echo "--- Trade_Scan ($(git rev-parse --abbrev-ref HEAD)) ---"
git status -sb | head -10
echo "unpushed: $(git rev-list --count @{u}..HEAD 2>/dev/null || echo '?')"
for r in ../DATA_INGRESS ../TS_Execution ../TradeScan_State; do
  [ -d "$r/.git" ] && { echo "--- $(basename "$r") ($(git -C "$r" rev-parse --abbrev-ref HEAD 2>/dev/null)) ---"; git -C "$r" status -s | head -6; }
done
```
Confirm BEFORE acting: on `main` (not a leftover feature branch from a prior/parallel session), working
tree clean OR every dirty entry understood, 0 unpushed, siblings not mid-edit. The closing SYSTEM_STATE
snapshot reports git state AT LAST CLOSE — this is the **LIVE** state, which differs when a parallel
session or external process mutated the tree after close (e.g. 2026-06-16: unexplained `D outputs/*`
deletions + an uncommitted `DATA_INGRESS broker_specs/*.yaml` state appeared post-close). A
dirty/divergent tree at startup is a FLAG — reconcile it before research, and never commit changes you
didn't make without confirming intent (Invariant #2 append-only / "if you didn't create it, surface
it"). (`[ -d ]` guards no-op from a worktree where `../` doesn't resolve to the sibling.)

### 1.9 Live basket pre-check (CONDITIONAL — skip for research-only sessions)

**Run this section only when the session involves live basket execution** (basket_producer.py is
running or about to start, or any `check_entry()` / API order flow is in scope).

Three mandatory assertions before ANY API order is placed. All three must pass; any failure is a
STOP — do not proceed with live basket interaction:

```python
# Paste into python or run as: python -c "..."
import subprocess, sys

procs = subprocess.run(
    ['tasklist', '/FI', 'IMAGENAME eq terminal64.exe', '/NH', '/FO', 'CSV'],
    capture_output=True, text=True
).stdout.strip().splitlines()
running = [p for p in procs if 'terminal64.exe' in p.lower()]

print(f"(1) terminal64.exe count: {len(running)}")
if len(running) != 1:
    print("FAIL — expected exactly 1 terminal64.exe; got", len(running))
    print("If count > 1: close all but the trading terminal and retry.")
    sys.exit(1)
print("    PASS")

# (2) + (3): run from TS_Execution
import importlib.util, pathlib
ts_exec = pathlib.Path(__file__).resolve().parents[3] / 'TS_Execution'
# Or just remind the operator:
print()
print("(2) Login + trade_mode: confirm active account matches allow-list in TS_Execution config.")
print("(3) trade_allowed: confirm MT5 terminal shows 'Trade' (not 'Expert' disabled or read-only).")
print()
print("If MT5 IPC dead → FAILURE_PLAYBOOK.md section 'MT5 API Pipe Dead'")
```

**Condensed checklist (memorise — faster than running the script):**
1. Exactly **one** `terminal64.exe` in Task Manager — the trading terminal, not a stale second instance.
2. Active account login + `trade_mode` matches TS_Execution allow-list (usually `DEMO` account during
   boarding; check `TS_Execution/config/` or the session's `basket_producer` log).
3. `trade_allowed == True` visible in MT5 terminal (top bar shows green "Trade" indicator, not
   read-only mode).

**Why this gate exists:** 2026-06-06 incident — API silently attached to a *second* `terminal64.exe`
(a stale instance from a prior session). All IPC calls succeeded, but order flow went to the wrong
account. ~30 min to isolate. The fix is trivially cheap; the failure mode is expensive.

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
| WATCH | Vault nav-layer DRIFT/STALE | 1.7 | Review the named maps; bump `verified:` (advisory — never blocks research) |

### Research triage

| Tier | Signal | Source | Action |
|---|---|---|---|
| RESUME | `NEXT:` lines in RESEARCH_MEMORY.md | 1.4 | Pick up the active arc |
| RESUME | Directives in `inbox/` ready to run | 1.5 | `/execute-directives` |
| OPEN | Open hypothesis arcs | 1.4 | `/hypothesis-testing` |
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
  • Vault maps DRIFT/STALE  →  review + re-verify  (advisory; ../TS_Obsidian_Vault/system/_sync.py)

=========================================================
Suggested first task: <Infra #1 if BLOCKER; else Active Charter focus if present and FRESH; else Research #1>
```

---

## Constraints

- **Read-only** except §1.1 which regenerates `SYSTEM_STATE.md` (authorized infrastructure snapshot — not a research mutation). No commits, no pipeline runs, no directive admission.
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
| 2026-06-16 | Vault nav-layer could silently drift from canonical | Added §1.7 advisory `_sync.py --summary` check |
| 2026-06-19 | §1.9 live pre-check verifies process health, not directive-config fidelity | Task: §1.9 to diff strategy_pool directive vs latest producer.log PRODUCER_START banner |
