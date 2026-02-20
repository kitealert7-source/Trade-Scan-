# Trade_Scan — Invariants (STATE‑GATED | FINAL)

**Status:** AUTHORITATIVE | SYSTEM LAW  
**Applies to:** Trade_Scan (all components, all agents)  
**Precedence:** Invariants > SOP_TESTING & SOP_OUTPUT > Agent Rules > Agents

---

## Purpose

This document defines **non‑negotiable, state‑gated invariants** for Trade_Scan.

Any violation **must abort the run immediately**.

---

## Invariant 1 — One Directive → One Atomic Run

- A run may start **only** with a single explicit human directive.
- If no directive exists, execution is forbidden.

---

## Invariant 2 — Linear State-Gated Execution

A Trade_Scan run exists in exactly one state at any time.

Allowed states (linear, non-reentrant):

- IDLE
- PREFLIGHT_COMPLETE
- PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
- STAGE_1_COMPLETE
- STAGE_2_COMPLETE
- STAGE_3_COMPLETE
- STAGE_3A_COMPLETE
- COMPLETE
- FAILED

Allowed transitions:

- IDLE → PREFLIGHT_COMPLETE
- PREFLIGHT_COMPLETE → PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
- PREFLIGHT_COMPLETE_SEMANTICALLY_VALID → STAGE_1_COMPLETE
- STAGE_1_COMPLETE → STAGE_2_COMPLETE
- STAGE_2_COMPLETE → STAGE_3_COMPLETE
- STAGE_3_COMPLETE → STAGE_3A_COMPLETE
- STAGE_3A_COMPLETE → COMPLETE

Rules:

- Preflight may execute only from IDLE.
- Stage-0.5 Semantic Validation may execute only from PREFLIGHT_COMPLETE.
- Stage-1 engine may execute only if state = PREFLIGHT_COMPLETE_SEMANTICALLY_VALID.
- Stage-2 engine may execute only if state = STAGE_1_COMPLETE.
- Stage-3 engine may execute only if state = STAGE_2_COMPLETE.
- Stage-3A snapshot finalization may execute only if state = STAGE_3_COMPLETE.
- COMPLETE may be reached only from STAGE_3A_COMPLETE.
- FAILED is terminal. No further execution is permitted.

---

## Invariant 3 — Approved Engines Only

Execution is restricted to the following **approved components only**:

Approved execution components are fixed and explicit:
Stage-1 execution must be invoked via run_stage1.py
Stage-1 emission must use execution_emitter_stage1.py
Stage-2 processing must use stage2_compiler.py
Stage-3 processing must use stage3_compiler.py
No other files may perform execution, emission, compilation, or aggregation.
Binary. No interpretation.

**Forbidden:**
Any file not listed above is non-authoritative by definition.
Execution, metrics, or transformation logic in any other file invalidates the run.
Execution from any vault/ directory is explicitly forbidden.

If detected → **FAIL**.

---

## Invariant 4 — No In‑Between Computation

Between any two stages:

- No new code may execute
- No data may be modified
- No metrics may be added, recomputed, or inferred

Stage boundaries are **hard execution barriers**.

Exception — Preflight Provisioning

Stage-0 (Preflight) is permitted to create or modify strategy artifacts
as part of directive-driven provisioning.

No mutation is permitted after PREFLIGHT_COMPLETE.
Stage-0.5 and later stages are strictly non-mutating.

---

## Invariant 5 — Atomicity

- A run must either reach COMPLETE
- Or emit **zero persistent artifacts**

Partial success does not exist.

---

## Invariant 6 — RUN_COMPLETE Gating

- Only runs marked RUN_COMPLETE are valid.
- Any downstream consumption before RUN_COMPLETE is forbidden.

---

## Invariant 7 — Artifact Immutability

- Stage‑1 execution artifacts are immutable once emitted.
- No overwrite, reinterpretation, or back‑mutation is permitted.

---

## Invariant 8 — Append‑Only Discipline

- New runs append only.
- Corrections require a new run.

---

## Invariant 9 — Failure Semantics

On **any** of the following:

- error
- ambiguity
- invariant violation
- missing required artifact

The system must:

1. Transition to FAILED
2. Abort immediately
3. Await a new human directive

No retries. No continuation.

---

## Final Rule

If an action:

- bypasses a stage
- inserts logic between stages
- executes outside approved engines
- or violates state order

The run is **invalid and must terminate**.

---

End of Trade_Scan Invariants (STATE‑GATED | FINAL)
