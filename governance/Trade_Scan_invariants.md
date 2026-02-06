# Trade_Scan — Invariants (FINAL)

**Status:** AUTHORITATIVE | SYSTEM LAW  
**Applies to:** Trade_Scan (all components, all agents)  
**Precedence:** Invariants > SOP_TESTING & SOP_OUTPUT > Agent Rules > Agents

---

## Purpose

This document defines **non‑negotiable invariants** for Trade_Scan.

If any behavior, code change, SOP update, or agent action violates an invariant below, the action **must be rejected**, regardless of convenience, performance, or perceived benefit.

Invariants define **category safety and system intent**, not implementation details.

---

## 1. System Authority Invariants

### Invariant 1 — Advisory‑Only System
Trade_Scan is strictly a **decision‑support system**.

It may:
- analyze trade ideas
- validate logic and economics
- generate artifacts for review

It must **never**:
- act
- decide
- approve
- promote
- execute

---

### Invariant 2 — No Execution Authority
Trade_Scan must never:
- place trades
- manage orders or positions
- connect to brokers or exchanges
- perform paper or live trading

Execution semantics are **out of scope**.

---

### Invariant 3 — Human‑Directed Research Only
Trade_Scan must never decide **what to research**.

- All activity must be tied to an explicit human directive
- No unguided exploration
- No agent‑initiated research questions

If no valid directive exists, Trade_Scan **must not run**.

---

## 2. Execution & Lifecycle Invariants

### Invariant 4 — One Directive → One Atomic Run
A Trade_Scan run is defined by a **single human directive**.

---

### Invariant 5 — Atomicity
A run must either:
- complete fully, or
- leave **no persistent artifacts**

Partial success does not exist.

---

### Invariant 6 — RUN_COMPLETE Gating
Only runs explicitly marked **RUN_COMPLETE** are valid.

- Failed or interrupted runs are treated as non‑existent
- Downstream consumption is forbidden otherwise

---

## 3. Capital & Economics Invariants

### Invariant 7 — Simulated Capital Only
Trade_Scan may model economics **only in simulation**.

Allowed:
- virtual capital curves
- hypothetical drawdown
- declared broker cost models

Forbidden:
- real account balances
- broker state
- execution‑dependent outcomes

All capital usage is **non‑operational**.

---

### Invariant 8 — Declared Cost Semantics
Execution costs must be:
- explicitly declared
- applied **exactly once**
- never inferred implicitly

Double‑counting or ambiguity invalidates a run.

---

## 4. Data & Artifact Invariants

### Invariant 9 — External Data Is Read‑Only
Market and reference data sources are **read‑only**.

- No modification
- No backfilling
- No silent fixes

If data is incorrect, Trade_Scan must **fail loudly**.

---

### Invariant 10 — No Artifacts on Failure
Failed or interrupted runs must emit **no persistent artifacts**.

---

### Invariant 11 — Execution Artifact Immutability
Authoritative execution artifacts emitted by Trade_Scan are immutable once emitted.

They constitute the single source of execution truth and MUST NOT be modified,
reinterpreted, or overwritten under any circumstances.


---

### Invariant 12 — Append‑Only Discipline
- New runs append data
- Existing artifacts are never overwritten
- Corrections require a **new run**

---

## 5. Validation & Computation Invariants

### Invariant 13 — Declared‑Scope Execution
Execution must be strictly constrained to the declared directive scope.

Undeclared assumptions are forbidden.

---

### Invariant 14 — No Post‑Run Re‑computation
Official metrics must **never** be recomputed after a run completes.

If a defect is suspected:
- report it
- initiate a new run

---

## 6. Results & Analysis Invariants

### Invariant 15 — One‑Pass Emission
Each run follows exactly one emission sequence:

**Execute → Capture → Compute → Emit**

No replay. No partial emission.

---

### Invariant 16 — One-Way Artifact Flow
Data and artifacts flow in one direction only:

Authoritative execution artifacts → Derived presentation artifacts → Human or agent analysis

Backflow from presentation or analysis into execution artifacts is strictly forbidden.

---

### Invariant 17 — Non‑Authoritative Analysis
Human and agent analysis:
- may explore
- may compare
- may hypothesize

It must **never** alter execution truth.

---

### Invariant 18 — Calibration-Based Admissibility

Symbols with calibration status `PASS` may be used for backtesting, validation, execution analysis, ranking, and promotion.

Symbols with calibration status `DERIVED_BACKTEST_ONLY` may be used for preliminary backtesting only and are strictly forbidden from execution, ranking, or promotion.

---



## 7. Agent Behavior Invariants

### Invariant 19 — Read‑Only by Default
Agents assume **read‑only** access unless explicitly permitted.

---

### Invariant 20 — No Rewriting History
Agents must not:
- modify RAW artifacts
- modify CLEAN artifacts
- edit emitted reports

---

### Invariant 21 — Fail‑Fast Requirement
On ambiguity or error, agents must:
- abort
- report clearly
- wait for human instruction

---

## 8. System Boundary Invariants

### Invariant 22 — No Downstream Integration
There is **no technical integration** with Trading_System.

- No APIs
- No shared state
- No automated handoff

All boundary crossings are **manual and human‑only**.

---

### Invariant 23 — No Coded Promotion
Promotion is never automated.

- No rankings as decisions
- No approval states
- No deployment signals

---

## 9. Governance Invariants

### Invariant 24 — Governance Over Convenience
If a choice exists between:
- convenience vs correctness
- speed vs clarity
- automation vs accountability

**Correctness, clarity, and accountability always win.**

---

### Invariant 25 — Invariant Stability
Invariants change **rarely and deliberately**.

---

### Invariant 26 — Violation Handling
Any invariant violation:
- invalidates the run
- requires disclosure
- requires corrective human action

---

## Final Rule

If a proposed change makes Trade_Scan:
- more autonomous
- more authoritative
- more coupled to execution
- less explainable to humans

Then the change **violates system intent and must be rejected**.

---

**End of Trade_Scan Invariants (FINAL)**

