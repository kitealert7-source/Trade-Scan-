---
name: design-challenge
description: Pre-scaling adversarial review of a finalized research design — catches ontology/population, selection-bias, and historical-analog errors that gates and schema validators cannot. Surfaces at most the 3 most dangerous flaws, then one bounded verdict (PROCEED / REVISE / ABANDON). Manual; invoke ONLY before corpus-building runs, large matrix sweeps, infra rollouts, or other durable-state writes. Distinct from /session-retro (backward, session-scoped) and from mechanical gates (namespace / window / F19).
---

# /design-challenge — Adversarial Research-Design Review

> **Design principle:** this skill is a **research-design adversary**, not a
> reviewer, brainstorm, or retro. It attacks ONE design that is already
> believed ready, in the territory automated defences cannot reach —
> **ontology, population, historical analog, bias.** It surfaces the single
> most dangerous flaw, not a list. Rationale:
> [`reference/design_notes.md`](./reference/design_notes.md).

`PROCEED` from this skill means **"no flaw found within the envelope"** — it
is **not** a proof that the design is correct. The skill is bounded; treat
its pass as "survived a time-boxed adversarial read," never as validation.

It runs **after** the mechanical gates (namespace, `window_validity_gate`,
F19 re-test, Idea Gate) and assumes they passed. It does not re-run them.

**Operating envelope** — exceeding any line means you have left the skill's job:

| | Limit |
|---|---|
| Wall-clock | 10–15 minutes |
| Findings surfaced | **≤ 3** (the most dangerous; one severe beats eight moderate) |
| Verdict | exactly 1 |
| Artifact | 1 pre-registered kill-criterion |

---

## Phase 0 — Self-gate (the anti-ceremony guard)

Invoke only when **both** hold:

1. The design is at the **probe → scale** boundary (the next action is the expensive one), and
2. Downstream cost is **high**: a corpus-building run, a large matrix sweep, an infra rollout, or any write to durable append-only state (ledgers / corpus).

If the design is **cheaper to run than to challenge** — e.g. a single
exploratory one-window backtest — print `PROCEED (below stakes threshold)`
and exit. The one-window run *is* the probe; do not tax cheap exploration.

The biggest failure mode of this skill is becoming ceremonial. Phase 0 plus
low invocation frequency are its only two defences — honour them.

---

## Phase 1 — Load (read-only)

Gather what the lenses need before judging:

- The finalized design / directive (the thesis, population, window, rules).
- **Institutional memory** for the analog lens — your cemetery:

// turbo

```bash
grep -nE "dead|FAIL|null|exhausted|parked|NO_TRADES|falsified" RESEARCH_MEMORY.md | head -40
```

Also scan the dead-architecture memory entries and the enforcement-plan
failure modes. The analog lens is only as good as the corpus you load here.

---

## Phase 2 — Adversarial lenses

Run **L1–L4 always**; fire **L5–L7 only when relevant**. Every finding must
**cite evidence** — a named population, a logged analog, a specific
assumption. A finding you cannot ground is a vibe; drop it. Stop at the **3
most dangerous** findings, ranked by blast radius (*contaminates durable
state* > *wastes a research arc* > *local error*).

### Mandatory

**L1 — Population / Ontology** *(highest ROI)*
- *Question:* "What is one row, what population does it sample, and what does the result actually represent?"
- *Output:* a one-line population definition, or a flagged conflation.
- *Catches:* FX-IDX-cross treated like FX-FX; episode/run conflation; the quarantine investigations that reduced to definition errors.

**L2 — Kill-Criterion** *(forces clarity, not compute-saving)*
- *Question:* "This design is false if ___ — and the cheapest test for that is ___."
- *Output:* the pre-registered kill-criterion + the smallest test that produces it. If none exists, the design may be unfalsifiably expensive → that itself is a finding.
- *Catches:* scaling to a 303 / 339 corpus before a one-window parity check.

**L3 — Historical Analog** *(the most distinctive lens)*
- *Question:* "Which corpse in the cemetery does this most resemble — and is its killing cause neutralized here?"
- *Output:* the closest logged failure (cited) + whether its cause is addressed or repeated in new clothing.
- *Catches:* ZREV S05–S15, ZPULL cross-asset null, SYMSEQ idea-60 — rebuilt as variants that F19's exact-match waves through. This is the **semantic complement to the mechanical F19 guard.**

**L4 — Selection / Survivorship Bias**
- *Question:* "Does the design assume its own conclusion? Where is the control / null cohort?"
- *Output:* a flagged embedded hypothesis, or confirmation a control exists.
- *Catches:* sampling only currently-qualifying members; **using CORE/WATCH/FAIL deployment verdicts as a research evaluator** (near-retired a strategy with real edge).

### Conditional (fire on relevance)

- **L5 — Minimal Thesis** *(multi-component designs):* "What is the irreducible core that carries the thesis, and can it be tested first?" Output is a sequencing decision, not a redesign.
- **L6 — Load-Bearing Assumptions** *(non-default engine/fill/session):* "What must be true but is unstated?" Catches fill-model-as-contract, `session_reset`→0-trades, vol_regime encoding.
- **L7 — Window / Alignment** *(only the residual `window_validity_gate` does not own):* warm-up leak, regime-flip misalignment. If the gate covers this design's class, **skip and say so.**

---

## Phase 3 — Verdict + kill-criterion

Exactly one verdict:

| Verdict | Means |
|---|---|
| **PROCEED** | No flaw found **within the envelope**. NOT a correctness proof. Execute as designed. |
| **REVISE(flaw)** | A named defect (ontology / assumption / bias) must change before execution. |
| **REVISE(probe-first)** | Design is sound but unproven — run the named cheapest probe before scaling. |
| **ABANDON** | Fatal flaw: embedded hypothesis, unfalsifiable, or a known dead end. |

The **kill-criterion is always emitted**, even on PROCEED. In Phase 1 of this
skill's own life, paste it by hand into the directive's rationale so the
eventual result can be checked against it; `REVISE(probe-first)` carries the
specific probe so [`/session-retro`](../session-retro/SKILL.md) can later
audit whether it was actually run before the design hit the corpus.

### Report template

```
=== DESIGN-CHALLENGE — <design id> — <YYYY-MM-DD> ===
Stakes: <corpus | matrix-sweep | infra | durable-write>   (Phase-0 passed)

Most dangerous findings (≤3, severity-ordered):
  1. [L<n> <lens>] <one line>   evidence: <population / analog ref / assumption>
  2. ...

VERDICT: <PROCEED | REVISE(flaw) | REVISE(probe-first) | ABANDON>
  reason: <one line>

KILL-CRITERION (pre-registered):
  This design is FALSE if <X>.
  Cheapest test: <the smallest experiment that produces X>.
==========================================
```

If no flaw surfaces in the envelope: report `PROCEED — no flaw found in
envelope (not a correctness proof)` plus the kill-criterion, and stop. Do
not keep digging past the envelope to manufacture a finding.

---

## Anti-patterns

- **Generating ideas or alternative designs** — it challenges *this* design, never proposes others.
- **Listing >3 findings / padding moderate ones** — one severe finding is the goal; volume dilutes attention.
- **Treating PROCEED as validation** — it is a bounded "no flaw found," nothing more.
- **Default-to-doubt** — default is trust; earn a non-PROCEED with a *named, evidenced* flaw or stay silent.
- **Re-running mechanical gates** — namespace / window / F19 / Idea-Gate already passed; never duplicate them.
- **Requesting more data when existing evidence suffices** — the move is the sharpest test on the data you have, not "go collect more."
- **Ceremony on cheap designs** — if running is cheaper than challenging, Phase 0 exits PROCEED.
- **Speculative architecture** — no observed/structural basis → no finding.

---

## When to invoke

- Before a **corpus-building run**, **large matrix sweep**, **infra rollout**, or any run whose results **write durable append-only state**.

## When NOT to invoke

- A single exploratory one-window backtest — that *is* the probe; just run it.
- Any design cheaper to run than to challenge.
- Anything the mechanical gates already own (namespace, window class, exact re-test).

---

## Related skills

| Skill | Relationship |
|---|---|
| [`/port-strategy`](../port-strategy/SKILL.md) | Produces the finalized design; design-challenge challenges it before scaling |
| [`/execute-directives`](../execute-directives/SKILL.md) | design-challenge gates the probe→scale step that precedes a large run |
| [`/session-retro`](../session-retro/SKILL.md) | Audits whether PROCEED designs honoured their pre-registered kill-criterion (the loop) |
| [`/hypothesis-testing`](../hypothesis-testing/SKILL.md) | Sibling research skill at a *later* lifecycle point (re-test of an existing baseline) |
| [`/sanity`](../sanity/SKILL.md) | The *lightweight* counterpart — a quick "what's missing?" over any plan or change. design-challenge is the heavy, durable-state-gating research-design review |

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
