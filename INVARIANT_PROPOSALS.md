# INVARIANT_PROPOSALS.md

Stable, append-only ledger for codified system invariants that originate as
proposals and graduate to implementation. Code and memory can cite entries
here by ID — unlike `SYSTEM_STATE.md`, this file is NOT regenerated.

**Rules:**
- Entries are append-only. Never delete or renumber.
- Status transitions: `PROPOSED → IMPLEMENTED | REJECTED`
- Each entry must name the enforcement artifact (test, gate, lint rule, or
  code comment) that makes the invariant machine-checkable.
- Code comments, RESEARCH_MEMORY, and auto-memory should cite this file
  by entry ID (e.g. `INVAR-001`), not `SYSTEM_STATE.md`.

---

## INVAR-001 — Leg-strategy dispatch completeness

**Proposed:** 2026-06-01  
**Status:** IMPLEMENTED  
**Enforcement:** `tools/run_pipeline.py::LEG_STRATEGY_DISPATCH` + `CONTINUOUS_HOLD_RULES`; runtime `LegDispatchError`  

Every recycle rule registered in `governance/recycle_rules/registry.yaml` must
appear in exactly ONE of:
- `LEG_STRATEGY_DISPATCH` — proposal-based legs (fire entry signals)
- `CONTINUOUS_HOLD_RULES` — always-open legs (rule handles the mechanic)

A registered rule absent from both raises `LegDispatchError` at dispatch
time — the failure is loud, not a silent fallthrough. This invariant was
proposed after the ZBND silent-fallthrough bug (2026-06-01) where an unrouted
rule produced no trades and no error.

**See also:** `[[mechanism-port-integration-points]]` memory entry.
