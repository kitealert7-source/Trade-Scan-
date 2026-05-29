# design-challenge Design Notes

Background and rationale for [`../SKILL.md`](../SKILL.md). The skill body
owns the procedure; this file owns the WHY. Converged over a multi-pass
design dialogue (2026-05-29).

---

## Why it exists: the residual after the gates

Most research failure classes in this repo are already owned by mechanisms:

- Window / alignment contamination → `window_validity_gate.py` (failure mode #2)
- Namespace / token errors → namespace gate
- Exact re-tests → F19 re-test guard
- Sign-flips → `check_entry` replay
- Implementation bugs → the test suite / break-tests

What is **left** is the class no validator can reliably catch: the research
*question itself is malformed* — wrong unit of analysis, invalid population,
an embedded hypothesis, a design that rhymes with a past corpse. Those are
exactly the failures that historically cost the most operator attention
(the quarantine / registry investigations repeatedly reduced to ontology,
not implementation). design-challenge's defensible territory is that residual —
**ontology, population, historical analog, bias** — and nothing the gates
already own.

---

## Not falsification, not compute-saving

The naive pitch ("kill bad ideas to save compute") is weak here: compute is
cheap relative to operator attention, and ambiguity is more expensive than
recomputation. So the value is **not** saving GPU hours. It is:

1. Stopping a confidently-wrong design from polluting **append-only ledgers
   / the corpus**, where it costs disproportionately more to detect and unwind.
2. Killing **ambiguity** fast — which is what the kill-criterion lens (L2)
   really does. The point of "this design is false if X" is not to kill the
   idea; it is to force the design to become *sharp*.

---

## PROCEED is bounded — not validation

PROCEED means "no flaw found within the 10–15 min / ≤3-finding envelope." It
is **not** a proof of correctness. This distinction is load-bearing: if
operators read PROCEED as validation, the skill becomes a false stamp of
approval and does more harm than not existing. The verdict wording in the
skill says so explicitly, and the kill-criterion is emitted even on PROCEED
so the design still carries a falsifiable claim forward.

---

## Why ≤3 findings, not 5

This is adversarial review, not retrospective coverage. The goal is the
single most dangerous flaw. One severe finding (an ontology error that
contaminates everything downstream) outweighs eight moderate ones, and a
long list dilutes the attention the skill is trying to protect. The cap
forces severity-ranking instead of accumulation.

---

## The two — and only two — defences against ceremony

The biggest risk is not a false negative; it is the skill degrading into a
ritual step run on everything. Its only protections are:

1. **Phase 0 self-gate** — skip designs cheaper to run than to challenge.
2. **Low invocation frequency** — corpus runs, large sweeps, infra rollouts,
   durable-state writes only.

No automation or tripwire is added, precisely to keep frequency low and
deliberate.

---

## Lens → failure-mode map

| Lens | Failure mode | Status of mechanical defence |
|---|---|---|
| L1 Population / Ontology | #1 malformed question | none — this skill's core |
| L3 Historical Analog | repeat-in-new-clothing | F19 covers only exact matches; L3 is the **semantic complement** |
| L4 Selection Bias | #3 governance-as-evaluator | none — judgment-only |
| L7 Window | #2 window contamination | mostly owned by `window_validity_gate` → usually skipped |

---

## Phasing — skill first, fields later

Phase 1 ships the **skill only**. Whether `kill_criterion` and
`cheapest_falsification` become **mandatory directive-schema fields** is a
Phase 2 decision, made after a few weeks of real use, on evidence:

- Does L3 catch real mistakes?
- Are kill-criteria high quality?
- Is the self-gate firing correctly?
- Does the skill actually save attention?

This ordering matches the repo's consistent record: process proves value
before enforcement. Building the field first would enforce a format whose
usefulness is unproven.

---

## What v1 deliberately omits

Schema fields (Phase 2) · INTENT_INDEX natural-language routing (manual
trigger by design) · telemetry · any automation / tripwire · session-close
coupling. Each is revisited only if real usage proves the skill catches
things real validators cannot.
