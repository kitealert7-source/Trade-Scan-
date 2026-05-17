# Hypothesis Document Schema

A **hypothesis document** is a formal YAML record of a basket-strategy
hypothesis test. It lives in `backtest_directives/hypotheses/` and is the
single source of truth for:

- *What* is being tested (motivation, baseline, variants)
- *Why* it's being tested (the reasoning that produced the hypothesis)
- *How success is judged* (acceptance criteria pre-declared)
- *What happened* (decision block filled at orchestrator close)
- *Lineage* (top-level `supersedes` links to predecessor hypotheses)

The `/basket-hypothesis-testing` orchestrator reads this file at Phase 1,
generates directives at Phase 3 (one per variant), and writes the
decision back at Phase 4. See
[`../../.claude/skills/basket-hypothesis-testing/SKILL.md`](../../.claude/skills/basket-hypothesis-testing/SKILL.md).

---

## Required top-level fields

| Field | Type | Notes |
|---|---|---|
| `id` | string | Machine-readable identifier. UPPER_SNAKE_CASE. Used as filename: `<ID>.yaml`. |
| `title` | string | Human-readable one-liner. |
| `class` | enum | v1 scope: `mechanic` \| `architecture`. Future: `parameter`, `composite`, `regime-gate`, `window-robustness`. |
| `status` | enum | `PROPOSED` (drafted, not invoked) → `ACTIVE` (orchestrator running) → `COMPLETED` (decision filled) → `ARCHIVED` (closed for record). |
| `created` | date | ISO date (YYYY-MM-DD). |
| `author` | string | `operator` for human-authored; agent name otherwise. |
| `supersedes` | string \| null | **Top-level lineage field.** Points to the `id` of a prior hypothesis this one replaces — set even when the predecessor never ran. Use `null` if standalone. This is intentionally separate from `decision.supersedes` (which records *deployment* supersession, not *hypothesis-spec* supersession). |
| `motivation` | text block | Free-form *why*. Cite prior commits, research-doc sections, memory files. |
| `baseline` | mapping | See §Baseline below. |
| `variants` | list | See §Variants below. |
| `acceptance_criteria` | mapping | See §Acceptance below. |
| `evidence_required` | mapping | See §Evidence below. |
| `session_links` | mapping | Commits, research doc references, memory file refs. |
| `decision` | mapping | Filled by orchestrator at Phase 4. See §Decision below. |

## Baseline

```yaml
baseline:
  directive: <baseline directive name, e.g. 90_PORT_H2_5M_RECYCLE_S14_V1_P00>
  rule: <baseline rule@version, e.g. H2_recycle@4>
  parquet_path: <relative path to baseline's results_basket_per_bar.parquet>
  key_metrics:                        # snapshot via §3.M canonical_metrics
    net_pct: <X>
    max_dd_pct: <X>
    ret_dd: <X>
    stake_usd: <X>
```

## Variants

Each variant becomes one directive at Phase 3. The orchestrator
generates the directive in INBOX/ with `hypothesis_ref` + `hypothesis_variant`
pointing back to this YAML.

```yaml
variants:
  - id: <variant id, e.g. H3_V1_P00>
    rule: <rule@version, e.g. H2_recycle@5>
    rule_build_required: <true | false>          # if true → orchestrator calls /port-strategy first
    architecture:
      basket_id: <e.g. H2>
      legs:                                       # list of leg specs
        - { symbol: EURUSD, direction: long, lot: 0.01 }
        - { symbol: USDJPY, direction: long, lot: 0.01 }
    stake_usd: <X>
    harvest_target_usd: <X>
    window:
      start: <YYYY-MM-DD>
      end:   <YYYY-MM-DD>
    rule_params:                                  # free mapping; passed verbatim to directive
      <key>: <value>
```

## Acceptance criteria

Structured comparisons. The orchestrator can mechanically check these
at Phase 4; operator adjudicates only when none apply (INCONCLUSIVE).

```yaml
acceptance_criteria:
  primary_metric: <one of: ret_dd | net_pct | max_dd_pct | etc>
  must_beat_baseline:
    <metric>: "> <value>"               # comparison operator + value
  must_not_be_worse_on:
    <metric>: "< <value>"               # absolute bounds
    survival: "<TARGET | EOD-positive | not-BLOWN>"
```

Supported comparison operators: `>`, `>=`, `<`, `<=`, `==`, `!=`.

## Evidence

```yaml
evidence_required:
  class: <single-window | multi-window-N | composite>
  parity_gate: <required | not_applicable>
  reason: <text block explaining the evidence choice>
```

`class` semantics — see §4.D in
[`../../.claude/skills/basket-hypothesis-testing/SKILL.md`](../../.claude/skills/basket-hypothesis-testing/SKILL.md).

## Session links

```yaml
session_links:
  prior_session_commits: [<short SHAs that produced the baseline / motivated this hypothesis>]
  research_doc: <path + section, e.g. "research/FX_BASKET_RECYCLE_RESEARCH.md §5.4d">
  memory_refs: [<memory file basenames>]
```

## Decision (filled by orchestrator at Phase 4)

```yaml
decision:
  outcome: <TBD | ACCEPT | REJECT | INCONCLUSIVE>
  decided_at: <UTC timestamp>
  decided_by: <operator | agent name>
  evidence_actual:
    class_achieved: <e.g., "single-window + parity-gated">
    canonical_metrics: { ... }            # per-variant, via §3.M
  reasoning: <text block — why ACCEPT / REJECT / INCONCLUSIVE>
  supersedes: <previous current-best id, if this becomes the new leader>
```

`decision.supersedes` is the **deployment-leadership** supersession (set
only on ACCEPT that promotes this hypothesis's variant past the prior
leader). Distinct from top-level `supersedes` which is the
**hypothesis-spec** lineage.

---

## Status lifecycle

```
draft .yaml in conversation
     │
     ▼
PROPOSED    ── orchestrator invocation ──>   ACTIVE
                                              │
                                              ▼
                              decision filled at Phase 4
                                              │
                                              ▼
                                         COMPLETED
                                              │
                              after analysis is no longer
                              referenced in current planning
                                              │
                                              ▼
                                          ARCHIVED
```

The orchestrator transitions `PROPOSED → ACTIVE` at invocation and
`ACTIVE → COMPLETED` at Phase 4 close. `COMPLETED → ARCHIVED` is a
manual transition (operator decision).

## Two kinds of supersession (don't conflate)

| Field | Set when | Captures |
|---|---|---|
| **Top-level** `supersedes` | At hypothesis *draft* time, even before any run | Spec evolution: H3_V2 replaces H3_V1 because we changed the design before testing |
| **Decision-block** `supersedes` | At Phase 4 close on ACCEPT | Deployment leadership: H3_V1 becomes the new current-best, supersedes whatever was previously the leader |

A hypothesis can have a top-level `supersedes` (we changed our mind on
the spec) *and* a decision-block `supersedes` (our changed-mind spec
also won the deployment race) — both fields populated, both meaningful.

---

## Directive linkage (the other direction)

Directives generated from this hypothesis carry two new fields under
their `test:` block:

```yaml
test:
  name: 90_PORT_H2_5M_RECYCLE_S16_V1_P00
  hypothesis_ref: <ID from this YAML>
  hypothesis_variant: <variant id from variants[]>
  ...
```

Audit trail: hypothesis YAML lists its variants → variants list maps to
directives → directives reference back to hypothesis. Closed loop.

---

## Naming conventions

- **Hypothesis ID** — `<FAMILY>_<DESCRIPTOR>_V<N>` (e.g. `H3_TREND_FOLLOW_V1`,
  `H2_ARCHITECTURE_4LEG_VS_B1`). UPPER_SNAKE_CASE.
- **Filename** — `<ID>.yaml` matching exactly. One hypothesis per file.
- **Variant ID** — `<HYPOTHESIS_PREFIX>_V<N>_P<NN>` where `P00` is the
  in-sample / first variant. Multiple variants share the same hypothesis
  YAML.

---

## When to draft a hypothesis (vs not)

Draft a hypothesis when:
- The test involves a non-trivial design decision worth recording
- You'll want to trace this decision in 6 months
- The variant requires a new rule class or a meaningful spec departure
- Acceptance criteria are non-obvious and could drift mid-test

Skip the formal hypothesis (run directives directly) when:
- It's a trivial re-run of an existing config (use `/rerun-backtest`)
- It's an exploratory probe with no fixed acceptance bar
- It's part of an active hypothesis test that's already been drafted
  (the variants are already enumerated there)
