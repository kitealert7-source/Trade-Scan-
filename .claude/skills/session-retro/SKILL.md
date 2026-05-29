---
name: session-retro
description: Pre-close operational retrospective — turns observed friction, robustness/resilience gaps, missed opportunities, and measured future-pressure trends into routed, capped follow-ups (Execute → sink / Monitor → watch-home / Ignore) plus exactly one HIGH ROI pick. Evidence-grounded, anti-speculation, backlog-resistant. Manual; run immediately before /session-close. Distinct from /session-close (transactional finalization) and per-skill friction logs (skill-bound).
---

# /session-retro — Operational Retrospective

> **Design principle:** this skill is a **router, not an essayist.** It
> converts what actually happened this session into follow-ups that each
> land in a durable home — or are dropped on purpose. It does NOT produce
> a standing advice document, and it does NOT propose architecture changes
> that no observed pain point motivated. Rationale:
> [`reference/design_notes.md`](./reference/design_notes.md).

Runs immediately before [`/session-close`](../session-close/SKILL.md).
Read-mostly: it writes only into homes that already exist (per-skill
friction logs, `SYSTEM_STATE.md ## Deferred Maintenance`, tasks, memory),
then hands off to session-close to commit them. It is **not** a code
review and **not** a status report — it surfaces observed friction,
observed failures, and near-future pressure only.

**Operating envelope** — if a run blows past this, you are auditing, not
retrospecting:

| | Target |
|---|---|
| Wall-clock | 5–10 minutes |
| Findings surfaced | 5–15 |
| HIGH ROI picks | exactly 1 |

---

## Phase 1 — Gather evidence (read-mostly)

Reconstruct the session you just lived, in **descending signal quality**.
The highest-value signals are in no log — only you saw them happen:

1. **Repeated manual intervention** — you did the same manual step ≥2×
2. **Repeated operator decisions** — the operator had to make the same kind of call repeatedly
3. **Pipeline failures / retries** — stages that failed, re-ran, or stalled
4. **Recovery actions** — resets, rollbacks, FSM repair, manual cleanups
5. **Agent observations** — fragility / ambiguity you noticed while working
6. **Logs (corroboration ONLY, never primary):** `.claude/logs/violations.jsonl`,
   `outputs/.session_state/pipeline_telemetry/*.jsonl`. v1 may skip these —
   in exploration / architecture / direction-change sessions the violation
   log is noise ≫ signal.

Then read back the open MONITOR watch-list so you can re-evaluate each item
this run, and find the window start (last close):

// turbo

```bash
git log --oneline -1 --grep="closing SYSTEM_STATE snapshot"   # window start = last close
grep -nE "^\s*-\s*\[MONITOR\]" SYSTEM_STATE.md || echo "(no active monitors)"
```

Window every finding to THIS session (commits since the close hash above).

---

## Phase 2 — Populate the five lenses

Fill **only** the lenses that have a grounded finding. An empty lens prints
`none observed this session`. **Never invent a finding to fill the
skeleton** — template-filling is the fastest way to make a retro worthless.

| # | Lens | The question | Working block (for the approval conversation) |
|---|---|---|---|
| 1 | **FRICTION** | What consumed time / attention without advancing objectives? | Issue · Impact · Root Cause · Frequency · Suggested Fix · Expected Benefit |
| 2 | **ROBUSTNESS** (avoid failure) | What single point of failure, fragile assumption, or hidden dependency surfaced? | Risk · Likelihood · Potential Damage · Mitigation · Priority |
| 3 | **RESILIENCE** (recover fast) | If today's failure recurred tomorrow, what cuts recovery time most? | Failure Scenario · Current Recovery Cost · Improvement |
| 4 | **MISSED OPPORTUNITIES** | What should have existed / been done earlier? | Observation · Why It Was Missed · Recommended Action |
| 5 | **FUTURE PRESSURE** | What becomes painful in 1–3 months, anchored to a measured trend? | Prediction (with the number) · Lead Time · Preventive Action |

**Evidence rules (hard):**

- **No fabricated metrics.** Likelihood / Priority / Confidence are
  categorical (H/M/L) or a date. A quantified saving ("cuts recovery 80%",
  "saves 2h") is allowed ONLY with a measured number behind it (telemetry
  duration, line-count delta) — otherwise state it qualitatively.
- **Future Pressure must be anchored.** Admissible only if you can show the
  trend (`RESEARCH_MEMORY.md 31 KB, +N KB/session → 40 KB ceiling in ~M
  sessions`). A forecast with no measurement is not a finding — drop it.
- **No speculative architecture.** If no concrete pain point was observed
  this session, there is no finding. This system is already mature; the
  biggest danger is inventing improvements because they look elegant.

---

## Phase 3 — Dispose + classify

Give every finding exactly one disposition:

| Disposition | Meaning | Destination |
|---|---|---|
| **EXECUTE** | Worth acting on | a durable act-sink (table below) + a priority tag |
| **MONITOR** | Real trend, threshold not yet crossed | watch-home: `## Deferred Maintenance` `[MONITOR]` + a named threshold |
| **IGNORE** | Interesting, not worth the cost | one line in the report, then dropped |

**EXECUTE act-sinks** — route by finding type (all already exist; no new infra):

| Finding type | Sink |
|---|---|
| Friction bound to a specific skill | that skill's `## Friction log` row (≤80 chars; [SELF_IMPROVEMENT](../SELF_IMPROVEMENT.md) flow) |
| Friction not bound to a skill | a task |
| Robustness gap needing a guard | a proposed gate / hook / invariant — **Protected Infra (invariant 6): plan + approval, do NOT self-apply** |
| Resilience gap | a [`FAILURE_PLAYBOOK.md`](../../../FAILURE_PLAYBOOK.md) entry, or a diagnostic / lineage-tool task |
| Missed opportunity | a MEMORY entry (so it is not re-missed), or a proposed invariant |
| Future pressure (actionable now) | `## Deferred Maintenance` with a lead-time, or a task with a trigger condition |

**EXECUTE priority tag:** `IMMEDIATE` (next session) · `SHORT` (1–2 weeks) ·
`STRATEGIC` (architecture-level; never self-applied — proposal only).

**MONITOR discipline** — both required, or it is not a monitor:

1. **A named threshold** that promotes it to EXECUTE (`promote when
   full-suite > 8 min`). No threshold → it is IGNORE, not MONITOR.
2. **Hard cap: ≤10 active MONITOR items.** Before adding the 11th you MUST
   either **promote** one (threshold effectively crossed → EXECUTE),
   **discard** one (stale / no longer true), or **merge** two related ones.
   Never let the watch-list grow unbounded. (Mirrors the 10-row friction-log cap.)

**IGNORE:** list each on one line under "Considered and dropped" so the
operator can override the call — but keep them one-liners. This section is
not a graveyard.

---

## Phase 4 — HIGH ROI CANDIDATE

After dispositioning, name **exactly one** EXECUTE item:

> If we fixed only one thing from this session, which produces the greatest
> reduction in future effort?

- Drawn **only** from the EXECUTE set (you cannot crown an Ignore or Monitor).
- **Mandatory when ≥2 EXECUTE findings exist**; with 0–1 it is self-evident or `none`.
- No ties. This is the single item handed to the next `/session-start` as its
  suggested first task.

This is the forcing function against "15 reasonable ideas, 0 executed."

---

## Phase 5 — Approve + land

Print the report (template below), then take **per-item approval** —
`approve / reject / modify` each finding. No batch yes, no implicit yes
(same gate as [`/skill-maintenance`](../skill-maintenance/SKILL.md)).

For each approved item, land it in its destination:

- **Friction row** → `Edit` the target skill's `## Friction log`
  (`| <date> | <≤80-char friction> | <≤80-char edit landed> |`).
- **MONITOR** → `Edit` `SYSTEM_STATE.md` `### Manual` under
  `## Deferred Maintenance`:
  `- [MONITOR] <metric> — promote when <threshold> (first seen <date>)`.
- **Deferred Maintenance (non-monitor)** → same Manual block, appropriate `[CATEGORY]`.
- **Task** → create it. **Memory** → draft the entry for the operator.
- **Protected-Infra proposal** → write the plan only; do NOT modify `tools/` / gates.

`session-retro` does **not** commit. Its writes sit on disk; the following
`/session-close` commits them in its normal flow. That is why retro runs
*before* close, not after.

### Report template

```
=== SESSION RETRO — <YYYY-MM-DD> ===
Window: since <last close short-hash>   Findings: <N>   (target 5–15)

── FRICTION ──                 (or: none observed this session)
  [EXECUTE·IMMEDIATE → friction-log:<skill>] <one line>
── ROBUSTNESS ──
  [EXECUTE·STRATEGIC → invariant proposal] <one line>
── RESILIENCE ──
  [EXECUTE·SHORT → FAILURE_PLAYBOOK] <one line>
── MISSED OPPORTUNITIES ──
  [EXECUTE·SHORT → memory] <one line>
── FUTURE PRESSURE ──
  [MONITOR] <metric + trend> — promote when <threshold>

── MONITOR watch-list ──       (active <K>/10)
  - [MONITOR] <existing + new, with thresholds>

── Considered and dropped (IGNORE) ──
  - <one line each>

★ HIGH ROI CANDIDATE
  <the single item>  →  <sink + priority>

Approve per item:  approve / reject / modify <n>
==========================================
```

If a session produced nothing worth surfacing, say so and exit — a clean
session has no retro. Do not manufacture findings.

---

## Anti-patterns

- **Template-filling** — an empty lens says `none observed`, it is not padded.
- **Fabricated metrics** — no invented percentages / hours without a measured number.
- **Unanchored Future Pressure** — a forecast with no trend line is dropped.
- **Speculative architecture** — no observed pain point → no finding.
- **MONITOR without a threshold**, or **>10 active monitors** — not allowed.
- **Self-applying a Protected-Infra change** — robustness guards are *proposals*; invariant 6 needs plan + approval.
- **Committing here** — session-retro stages; `/session-close` commits.
- **Exceeding the envelope** — more than ~15 findings means you are auditing, not retrospecting.

---

## When to invoke

- Immediately before `/session-close`, on any substantive working session.

## When NOT to invoke

- Trivial read-only / Q&A session — nothing to retro.
- Mid-task pause (resuming the same session) — wait for a real session end.

---

## Related skills

| Skill | Relationship |
|---|---|
| [`/session-close`](../session-close/SKILL.md) | Runs right after; commits what retro stages. Retro deliberately does not touch close. |
| [`/session-start`](../session-start/SKILL.md) | Sibling bookend at the other end of the session; the HIGH ROI pick is intended as the next start's first task (session-start does not yet auto-read the MONITOR list — see design notes) |
| [`/skill-maintenance`](../skill-maintenance/SKILL.md) | Audits the friction-log rows retro creates for format compliance |
| [`SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md) | The per-skill friction-log flow retro routes Execute-friction into |

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
