# Diagnostic Contract — Framework-Wide Design Proposal

**Status:** PROPOSAL (awaiting operator approval) · **Date:** 2026-06-30 · **Author:** agent session (VOLPULL index migration retro)
**Supersedes:** the 2026-06-30 "Fail-Fast Standard" draft — repositioned per operator review from a fail-fast patch into a framework-wide contract.

> A single structured **diagnostic contract** that **every subsystem speaks** when it blocks — so a failure communicates not just *that* it happened, but *why*, *how to fix it*, and *what to do next*; and so the system can answer "which class of problem costs us the most" without mining log text.
>
> The goal is to standardize how the system **communicates** problems, not just how it **detects** them. Detection is already strong (~30 gates); communication is the gap.

---

## 1. Problem & positioning

The fail-fast surface is large and heterogeneous: **~30 distinct gate exception classes**, each emitting an **ad-hoc string**, with **no shared contract**. The *reason* and *remedy* live only in the gate author's head or an unread governance doc; the caller sees `FAIL: X` and re-derives the rest.

**This is not a fail-fast polish — it is the system's missing common language for problems.** Every subsystem that can block should speak it:

`Admission · Namespace · Classifier · Semantic Validator · Runtime · Stage-2 Compiler · Reporting · Promotion`

**Evidence — three blocks from the 2026-06-30 VOLPULL migration, each costly precisely because the gate was protective-only:**

| Gate output (actual) | What was missing | Cost |
|---|---|---|
| `UNKNOWN_NESTED_KEY: volatility_filter: ['cooldown_bars']` | cause (schema-regression) + remedy (param → strategy constant) | minutes + a code dig |
| `NO_TRADES` (0 trades) | cause (`session_reset` default expires daily pending entries) + remedy (`session_reset: none`) | ~an hour of instrumented debugging |
| `STAGE -0.21 CLASSIFIER GATE: identity change` | a clean registered-vs-current diff + remedy (allocate a new idea_id) | several turns of re-derivation |

The gates **knew** all of this at block time. They just didn't emit it in a form the caller could consume.

---

## 2. The contract

**Six emitted fields** (operator-revised — `NEXT ACTION` added):

```
ERROR        what failed (headline)
CAUSE        why it failed (mechanism, not a restatement)
SOURCE       the invariant / gate / code location that enforces it
REMEDY       what change fixes the problem
NEXT ACTION  what the pipeline/agent should DO
AUTO-FIX     Yes | No
```

**Plus structured metadata** on the object (queryable, not necessarily rendered):

```
CODE      stable machine id      e.g. IDENTITY_CHANGE
CATEGORY  IDENTITY | NAMESPACE | SCHEMA | ENGINE | EXECUTION | DATA | GOVERNANCE | FSM
DOC_REF   link to the governing doc / invariant
CONTEXT   structured payload (registered-vs-current tuple, field name, counts, ...)
```

### Two distinctions that carry the design

**REMEDY vs NEXT ACTION** (the operator's key addition). They answer different questions:
- **REMEDY** — *what fixes the problem?* → "Allocate a new idea_id for NAS100."
- **NEXT ACTION** — *what should the pipeline/agent do right now?* → one of a closed verb set:
  `Stop-and-request-approval | Retry-after-autofix | Continue | Abort-directive`

This stops the agent from **inferring workflow out of prose**. The remedy tells a human what to change; the next-action tells the machine what to do.

**CATEGORY** turns failures into analytics. Six months on, *"which category costs us the most time?"* is a `GROUP BY category` over the telemetry the pipeline already writes (`outputs/.session_state/pipeline_telemetry/`), not a log-text mining exercise.

### Rendered example (`IDENTITY_CHANGE`)

```
❌ IDENTITY_CHANGE                              [category: IDENTITY]
ERROR       : strategy identity differs from the registered idea.
CAUSE       : (family, model, symbol, timeframe) defines the idea identity; it is
              immutable within an idea_id.
SOURCE      : tools/classifier_gate.py Identity Guard (admission Stage -0.21)
              Registered: (MR, VOLPULL, US30,  1D)
              Current   : (MR, VOLPULL, NAS100, 1D)
REMEDY      : allocate a new sequential idea_id for NAS100; do not reuse idea 73.
NEXT ACTION : Stop-and-request-approval   (allocating an idea is a research decision)
AUTO-FIX    : No
DOC_REF     : CLAUDE.md "Strategy Identity" · reference_idea_identity_model
```

---

## 3. Architecture — the catalog is the single source of truth

The operator's central requirement: **gates contain no explanatory prose.** A gate raises only its `code` + `context`:

```python
raise Diagnostic(code="IDENTITY_CHANGE", context={"registered": (...), "current": (...)})
```

Everything else lives in **one catalog** (`governance/diagnostics/catalog.yaml`), keyed by `code`:

```yaml
IDENTITY_CHANGE:
  category:    IDENTITY
  cause:       "(family, model, symbol, timeframe) defines the idea identity; immutable within an idea_id."
  remedy:      "Allocate a new sequential idea_id for {current.symbol}; do not reuse {context.idea_id}."
  next_action: stop_and_request_approval
  auto_fixable: false
  doc_ref:     "CLAUDE.md#strategy-identity"
```

The catalog owns: **cause · remedy · next_action · auto_fixable · doc_ref · category.** This separation is what keeps the system maintainable as it grows — remedy text lives in one place, gates stay logic-only, and the rendered output is uniform by construction.

Four pieces, all additive (no change to any gate's *decision*):
1. **`Diagnostic` carrier** — dataclass; gates raise it (wrapping the existing ~30 exceptions, or replacing them incrementally).
2. **Catalog** — `code → {category, cause, remedy, next_action, auto_fixable, doc_ref}`.
3. **Renderer** — `render(diag) -> str`; the single output path for every gate failure.
4. *(Phase 2)* **Auto-fix dispatch** — see §6.

---

## 4. Auto-fix & next-action taxonomy

`auto_fixable` is an **allow-list** (defaults `false`); a code becomes auto-fixable only via an explicit catalog entry + a tested fixer. Anything touching research, governance vocabulary, or design choice is never auto-fixed.

| Code | Category | Auto-fix | Next action |
|---|---|---|---|
| `MISSING_APPROVED_MARKER` | FSM | **Yes** | Retry-after-autofix |
| `SWEEP_NOT_RESERVED` | NAMESPACE | **Yes** | Retry-after-autofix |
| `SIGNATURE_DRIFT` | FSM | **Yes** | Retry-after-autofix |
| `DAILY_PENDING_ENTRY_EXPIRED` | EXECUTION | **Propose** | Stop-and-request-approval (with the exact `session_reset: none` patch attached) |
| `UNKNOWN_TOKEN` | NAMESPACE | No | Stop-and-request-approval |
| `UNKNOWN_NESTED_KEY` (schema-removed) | SCHEMA | No | Stop-and-request-approval |
| `IDENTITY_CHANGE` | IDENTITY | No | Stop-and-request-approval |
| `REPEAT_FAILED` | GOVERNANCE | No | Stop-and-request-approval |

---

## 5. Subsystem coverage

The contract is framework-wide; each blocking point migrates to it over time. Initial mapping of where the categories live:

| Subsystem | Example codes | Category |
|---|---|---|
| Admission / Idea Gate | `REPEAT_FAILED` | GOVERNANCE |
| Namespace | `UNKNOWN_TOKEN`, `SWEEP_NOT_RESERVED` | NAMESPACE |
| Canonicalizer | `UNKNOWN_NESTED_KEY` | SCHEMA |
| Classifier | `IDENTITY_CHANGE` | IDENTITY |
| Semantic Validator | `ENGINE_OWNED_FIELDS` | ENGINE |
| Runtime / Stage-1 | `NO_TRADES`, `DAILY_PENDING_ENTRY_EXPIRED` | EXECUTION |
| Stage-2 Compiler / Reporting | compile/aggregate failures | EXECUTION/DATA |
| Promotion | quality-gate fails | GOVERNANCE |
| FSM | `MISSING_APPROVED_MARKER`, `SIGNATURE_DRIFT` | FSM |

---

## 6. Phasing (revised — start with TWO gates)

Per operator: prove the contract on the two most painful gates before any rollout, to avoid redesigning it mid-migration.

**Phase 1 — the contract + a real proof:**
- `Diagnostic` object · catalog · renderer · **CI enforcement** (§8)
- Convert exactly **two** gates: **`IDENTITY_CHANGE`** (classifier) and **`UNKNOWN_NESTED_KEY`** (canonicalizer) — the two biggest pain points this session.
- Use them in real runs. If the contract feels right, the rest become mechanical conversions.

**Phase 2 — breadth + auto-fix dispatch:** convert the remaining high-traffic gates (namespace, sweep, semantic validator, idea gate, `NO_TRADES`) and add the `auto_fixable` fixers.

**Phase 3 — long tail + the remediation loop** (§7).

---

## 7. Future capability (noted, not built) — agent remediation loop

The contract *naturally enables* a clean remediation loop, instead of retries hardcoded into individual gates:

```
Gate → Diagnostic
        │
        ├─ AUTO-FIX == Yes →  apply fixer  →  retry once  →  Continue
        │                                         └─ still fails → present operator
        └─ AUTO-FIX == No  →  present operator the diagnostic (NEXT ACTION drives the verb)
```

Keep it in mind as the payoff; do not build it in Phase 1. Once `Diagnostic` + `next_action` exist, this loop is ~30 lines in one place, not N gates.

---

## 8. Enforcement (anti-decay — per `feedback_enforceable_mechanisms_only`)

A contract gates *may* use decays to today's heterogeneity. Make it structural:
- **CI test:** every gate-raised exception carries a `Diagnostic` whose `code` is registered in the catalog, and every catalog entry has all fields non-empty with a valid `category` + `next_action`. A bare-string gate failure fails CI. (Mirrors the `abi_audit` triple-gate pattern.)
- **Single output path:** gates may not `print()` a failure or `raise RuntimeError(<prose>)` at gate sites — pre-commit grep-guard; all failure text goes through `render()`.

---

## 9. Risks

- **Stale REMEDY text** — confidently-wrong "how to fix" is worse than none. Mitigation: catalog is the single home (one place to keep current); `source` + `doc_ref` always cite live code/docs so a reader can verify.
- **Over-eager auto-fix** — `auto_fixable` defaults `false`; allow-list only, each with a tested fixer; never auto-fix a research/governance/identity decision.
- **Migration cost** — ~30 classes is real work; the two-gate Phase 1 de-risks the contract before that cost is incurred.

---

## 10. ROI & recommendation

The three §1 blocks cost the better part of a session. The two-gate Phase 1 alone would have turned the worst two (`IDENTITY_CHANGE`, `UNKNOWN_NESTED_KEY`) into self-explaining stops with remedy + next-action inline. The `AUTO-FIX`/`NEXT ACTION` pair then lets the agent clear the mechanical codes (`MISSING_APPROVED_MARKER`, `SWEEP_NOT_RESERVED`, `SIGNATURE_DRIFT` — all hand-fixed this session) without stopping.

The running **identity-lint chip** (`task_e1a2249e`) is the **pilot instance**: its spec'd output is already the diagnostic shape, so it slots into the catalog as `IDENTITY_TUPLE_MISMATCH` rather than needing a rewrite — Phase 1's first brick is already being laid.

**Recommendation:** approve Phase 1 (contract + catalog + renderer + CI enforcement + the **two** gates). Additive — no change to gate *decisions*, only to how they *report*. Potential to become a foundational piece: it standardizes how the whole system communicates problems.

**Open decisions for the operator:**
1. Approve the two-gate Phase 1 scope.
2. Catalog location `governance/diagnostics/catalog.yaml` — OK?
3. Confirm the `CATEGORY` enum (`IDENTITY · NAMESPACE · SCHEMA · ENGINE · EXECUTION · DATA · GOVERNANCE · FSM`) and the `NEXT ACTION` verb set (`Stop-and-request-approval · Retry-after-autofix · Continue · Abort-directive`).
4. Confirm the rename to **Diagnostic Contract**.
