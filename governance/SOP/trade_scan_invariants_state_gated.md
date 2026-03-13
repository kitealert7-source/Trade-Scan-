# Trade_Scan — Invariants (STATE‑GATED | FINAL)

**Status:** AUTHORITATIVE | SYSTEM LAW  
**Applies to:** Trade_Scan (all components, all agents)  
**Precedence:** Invariants > SOP_TESTING & SOP_OUTPUT > Agent Rules > Agents

---

## Purpose

This document defines **non‑negotiable, state‑gated invariants** for Trade_Scan.

Any violation **must abort the run immediately**.

---

## Invariant 1 — One Directive → Planned Run Set

- Execution may start **only** from a single explicit human directive.
- The directive is expanded into an on-disk run registry (`TradeScan_State/registry/run_registry.json`).
- Each strategy/symbol execution unit is an independent planned run.
- If no directive exists, execution is forbidden.

---

## Invariant 2 — Linear State-Gated Execution

A Trade_Scan run exists in exactly one state at any time.

Allowed states (linear, non-reentrant):

- IDLE
- PREFLIGHT_COMPLETE (Stage 0)
- STAGE_0_5_SEMANTICALLY_VALID
- STAGE_0_55_SEMANTIC_COVERAGE_COMPLETE
- STAGE_0_75_DRY_RUN_COMPLETE
- STAGE_1_COMPLETE
- STAGE_2_COMPLETE
- STAGE_3_COMPLETE
- STAGE_3A_COMPLETE (Manifest Bound)
- STAGE_4_COMPLETE (Portfolio Evaluation)
- COMPLETE
- FAILED

Allowed transitions:

- IDLE → PREFLIGHT_COMPLETE
- PREFLIGHT_COMPLETE → STAGE_0_5_SEMANTICALLY_VALID
- STAGE_0_5_SEMANTICALLY_VALID → STAGE_0_55_SEMANTIC_COVERAGE_COMPLETE
- STAGE_0_55_SEMANTIC_COVERAGE_COMPLETE → STAGE_0_75_DRY_RUN_COMPLETE
- STAGE_0_75_DRY_RUN_COMPLETE → STAGE_1_COMPLETE
- STAGE_1_COMPLETE → STAGE_2_COMPLETE
- STAGE_2_COMPLETE → STAGE_3_COMPLETE
- STAGE_3_COMPLETE → STAGE_3A_COMPLETE
- STAGE_3A_COMPLETE → STAGE_4_COMPLETE
- STAGE_4_COMPLETE → COMPLETE

Rules:

- Preflight may execute only from IDLE.
- Stage-0.5 Semantic Validation may execute only from PREFLIGHT_COMPLETE.
- Stage-0.55 Coverage may execute only from STAGE_0_5_SEMANTICALLY_VALID.
- Stage-0.75 Dry Run may execute only from STAGE_0_55_SEMANTIC_COVERAGE_COMPLETE.
- Stage-1 engine may execute only if state = STAGE_0_75_DRY_RUN_COMPLETE.
- Stage-2 engine may execute only if state = STAGE_1_COMPLETE.
- Stage-3 engine may execute only if state = STAGE_2_COMPLETE.
- Stage-3A snapshot finalization may execute only if state = STAGE_3_COMPLETE.
- Stage-4 portfolio evaluation may execute only from STAGE_3A_COMPLETE.
- COMPLETE may be reached only from STAGE_4_COMPLETE.
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

## Invariant 10 — Research Layer Isolation (Symmetric Boundary)

The `research/` directory is structurally outside the FSM scope.

**Pipeline → Research (Outbound):**

- Code executing within the FSM (Preflight through Stage‑4) MUST NOT import any module from `research/`.
- No pipeline stage may read configuration, data, or code from `research/`.

**Research → Pipeline (Inbound):**

No module inside `research/` may:

- Import `PipelineStateManager` or `DirectiveStateManager`
- Write to `TradeScan_State/runs/`
- Modify `TradeScan_State/backtests/Strategy_Master_Filter.xlsx` or any registry artifact
- Alter any `run_state.json` or `directive_state.json`

The boundary is **symmetric and absolute**.

Violation in either direction invalidates the run or contaminates the research artifact.

---

## Final Rule

If an action:

- bypasses a stage
- inserts logic between stages
- executes outside approved engines
- or violates state order

The run is **invalid and must terminate**.

---

## Invariant 11 — Clean Repository Rule

- The Trade_Scan repository is immutable during pipeline execution.
- All runtime artifacts (runs, registries, backtests, reports, sandbox outputs) MUST be written exclusively to `TradeScan_State/`.
- Any tool or workflow attempting to write runtime artifacts inside the repository constitutes a governance violation.

---

## Final Ruleof Trade_Scan Invariants (STATE‑GATED | FINAL)

End of Trade_Scan Invariants (STATE‑GATED | FINAL)
