# Trade_Scan Agent Rules (FINAL)

**Status:** ACTIVE | ENFORCEMENT LAYER  
**Applies to:** All AI agents operating within Trade_Scan  
**Hierarchy:** SOP_TESTING, SOP_OUTPUT > Agent Rules > Agents

---

## 1. Role of This Document

This document defines **how agents must behave**.

It does **not** define system truth, execution semantics, or research authority.

- SOPs define authority and invariants
- Agent rules enforce compliant behavior
- Agents MUST comply or abort

If any conflict exists, **SOPs always override agent rules**.

---

## 2. Scope of Agent Authority

Agents:
- MAY assist with execution, validation, and analysis **only as permitted by SOPs**
- MAY read completed artifacts
- MAY generate advisory analysis

Agents MUST NOT:
- make decisions
- judge strategy quality
- promote, rank, or recommend strategies
- initiate new runs without explicit human instruction

---

## 3. Run Lifecycle Awareness (MANDATORY)

Agents MAY operate **only** on runs that satisfy:

```
run_status == RUN_COMPLETE
```

Agents MUST NOT:
- act on partial runs
- resurrect failed runs
- infer results from incomplete artifacts

---

## 4. Artifact Authority Rules

Agents MUST respect artifact authority boundaries:

- Authoritative execution artifacts (emitted by SOP_TESTING) are immutable
- Derived presentation artifacts (emitted by SOP_OUTPUT) are read-only
- Exploratory or agent-generated artifacts are non-authoritative

Rules:
- Authoritative and presentation artifacts MUST NOT be modified
- No derived or agent-generated output may flow back into execution artifacts


---

## 5. Read / Write Permissions

Default posture: **READ-ONLY**

Agents MAY write only when explicitly permitted, and only to:
- RESEARCH artifacts
- logs
- temporary working files

Agents MUST NOT:
- overwrite existing artifacts
- edit emitted Excel reports
- modify CSVs or JSON produced by SOP_TESTING

Append-only discipline is mandatory.

---

## 6. No Re-computation Rule

Agents MUST NOT:
- recompute official metrics
- regenerate statistics already emitted
- "fix" numbers post-hoc

If a defect is suspected:
- Report the issue
- Request a new run
- Do NOT patch artifacts

---

## 7. Determinism & Reproducibility

Agents MUST:
- prefer deterministic operations
- avoid hidden randomness
- document assumptions explicitly

Non-deterministic behavior:
- must be declared
- must never affect authoritative artifacts

---

## 8. Failure Handling

On any error or ambiguity, agents MUST:
- fail fast
- stop execution
- report the issue clearly

Agents MUST NOT:
- retry silently
- partially complete tasks
- mask failures

---

## 9. Communication Rules

Agents MUST:
- state uncertainty explicitly
- request clarification when authority is unclear
- reference the governing SOP when explaining actions

Agents MUST NOT:
- guess intent
- assume permission
- invent governance rules

---

## 10. Hard Prohibitions

Agents are strictly forbidden from:
- executing real or paper trades
- modifying SOP files
- bypassing governance constraints
- mutating RAW or CLEAN artifacts
- influencing future research direction

---

## 11. Enforcement

Any violation of this document requires:
- immediate abort
- explicit disclosure
- corrective human instruction

---

**End of SOP_AGENT_CONDUCT**

