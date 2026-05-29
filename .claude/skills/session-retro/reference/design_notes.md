# session-retro Design Notes

Background and rationale for non-obvious choices in
[`../SKILL.md`](../SKILL.md). The skill body owns the procedure; this file
owns the WHY. Converged over a three-pass design dialogue (2026-05-29).

---

## Why a separate skill, run *before* close — not a step inside it

[`/session-close`](../../session-close/SKILL.md) optimizes for
*deterministic transactional finalization* (commit, gate, push, snapshot)
and its design notes explicitly resist adding reflective steps — "the
natural tendency … is to add 'a quick check at session-close'." Retro is
reflective / generative work: wrong altitude for the transactional
conductor.

Running it *before* close means its outputs (friction rows, Deferred
Maintenance entries, tasks) already sit on disk when close runs, so close
commits them with zero new logic. It is the third bookend:
`session-start` (orient) → *work* → `session-retro` (reflect + route) →
`session-close` (finalize).

---

## Router, not essayist — the sink discipline

A skill whose job is to *generate suggestions* is, by default, a machine
for producing decaying advice — exactly what the project's
*enforceable-mechanisms-only* doctrine warns against (optional docs
decay and become worse than nothing; the default answer to vague friction
is "nothing to build").

What makes this skill legitimate: every finding terminates in a durable
home that **already exists**, or is dropped on purpose. The prose is not
the product; forcing each observation to earn a tracked home (or die) is.
A **priority tag is not a destination** — `[STRATEGIC]` left inside a
report still evaporates. Hence every Execute finding carries both a
priority *and* a sink.

---

## Three dispositions, and the MONITOR trap

Execute / Monitor / Ignore. MONITOR is the dangerous one — "we're keeping
an eye on it" is what people say about things they have forgotten. Two
rules keep it honest:

1. **A named threshold** makes it self-terminating: the next retro
   auto-promotes when the line is crossed. No threshold → it is IGNORE.
2. **A visible home that already exists:** `SYSTEM_STATE.md ##
   Deferred Maintenance ### Manual`, defined there as "tracked
   opportunities, NOT problems" — almost exactly MONITOR's semantics. A
   `[MONITOR]` prefix disambiguates it from actionable deferrals, and
   retro Phase 1 reads it back next session. Zero new storage — which
   honors "don't build data collection before you've proven the reports
   are useful."

**Hard cap of 10 active monitors** (promote / discard / merge on overflow)
mirrors the friction-log 10-row cap and stops the watch-list becoming the
entropy sink the whole skill is designed to avoid.

---

## Signal ranking — why violations.jsonl is demoted

Valuable sessions here are often exploration, architecture discussion,
challenging assumptions, and changing direction — sessions in which
`.claude/logs/violations.jsonl` is noise ≫ signal. The highest-value
signals (repeated manual intervention, repeated operator decisions,
recovery actions) exist in **no log** — only in the agent's lived
experience of the session. So the primary source is the agent
reconstructing what it just did; logs are corroboration only, and v1
skips telemetry mining entirely. Many systems fail by collecting data
instead of solving problems; this one starts shallow.

---

## Anti-speculation + grounded Future Pressure

Section 5 (Future Pressure) asks for prediction, which is inherently
speculative, while the anti-speculation rule bans speculation — a latent
contradiction. Resolved by requiring every forecast to be **anchored to a
measurable present trend** (a number you can show growing), never a vibe.
"RESEARCH_MEMORY.md is 31 KB, +N/session → 40 KB ceiling in ~M sessions"
is admissible; "parallel execution will get painful" is not. That turns
§5 from "imagine future pain" into "extrapolate an observed metric."

---

## Operating envelope

5–10 minutes, 5–15 findings, exactly 1 HIGH ROI pick. Past that you are
running a full audit every session, which is the failure mode that kills
retrospectives. The HIGH ROI capstone forces prioritization over
accumulation: the single highest-leverage Execute item, handed forward to
the next `session-start`.

---

## What v1 deliberately omits

- **No INTENT_INDEX natural-language routing** — manual trigger by design;
  prove value before wiring discovery (and the anti-naked-fuzzy intent
  doctrine + `MAX_INTENTS` budget make a routing entry a real cost).
- **No session-close tripwire** — do not touch close. Run retro manually
  for a few weeks; only then decide whether "retro not run this session"
  deserves a reminder or enforcement.
- **No telemetry mining** — `pipeline_telemetry` parsing is a later move,
  added only if the reports prove worth the build.
