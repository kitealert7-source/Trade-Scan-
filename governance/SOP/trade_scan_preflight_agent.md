# Trade_Scan — Agent Execution Contract (COMPACT)

**Status:** ACTIVE | ENFORCEMENT SUMMARY  
**Audience:** All agents executing or assisting Trade_Scan runs

This document is the **only agent-facing execution contract**.  
It is intentionally short. If a rule is not here, it is enforced elsewhere (invariants, SOPs, code).

---

## 1. What an Agent Is Allowed to Do

Agents may:

- Validate directives (preflight, read-only)
- Execute **approved engines only**, in order
- Read RUN_COMPLETE artifacts
- Produce advisory analysis (non-authoritative)

Agents must assume **READ-ONLY by default**.

---

## 2. Fixed Execution Path (NON-NEGOTIABLE)

A run follows exactly this path:

DIRECTIVE
  ↓
Preflight Check (ALLOW or BLOCK)
    └─ Mandatory Engine Integrity Check
       python tools/verify_engine_integrity.py
       - MUST execute
       - MUST exit with code 0 (PASS)
       - Failure or omission → BLOCK
  ↓
Stage-0.5 Semantic Validation
  ↓
Stage-1 Engine (run_stage1.py)
  ↓
Stage-1 Emitter (execution_emitter_stage1.py)
  ↓
Stage-2 Engine (stage2_compiler.py)
  ↓
Stage-3 Engine (stage3_compiler.py)
  ↓
Stage-3A Snapshot Finalization (pipeline-enforced)
  ↓
STOP

Stage-1 MUST NOT execute unless Stage-0.5 passes.

Stage-3A MUST execute before STOP.
Failure to finalize snapshot → FAILED state.

There are **no alternate paths**.

---

## 3. Approved Engines (WHITELIST)

Agents may invoke **only** the following entrypoints:

- Stage-1 execution: `run_stage1.py`
- Stage-1 emission: `execution_emitter_stage1.py`
- Stage-2 processing: `stage2_compiler.py`
- Stage-3 processing: `stage3_compiler.py`

All other files are **non-authoritative libraries**.

If an agent executes logic outside these → **FAIL**.

---

## 4. State Rules (BINARY)

Agents must respect run state:

- Preflight may run only from `IDLE`
- Stage-0.5 Semantic Validation may run only after `PREFLIGHT_COMPLETE`
- Stage-1 may run only after `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`
- Stage-2 may run only after `STAGE_1_COMPLETE`
- Stage-3 may run only after `STAGE_2_COMPLETE`
- Stage-3A may run only after `STAGE_3_COMPLETE`- COMPLETE may be reached only after `STAGE_3A_COMPLETE`

- `FAILED` is terminal

State violations → **ABORT**.

---

## 5. Absolute Prohibitions

Agents must NEVER:

- Insert code or computation between stages
- Recompute metrics after Stage-1
- Modify RAW or CLEAN artifacts
- Edit emitted CSVs / Excel files
- Bypass preflight
- Execute internal engine modules (`main.py`, `execution_loop.py`)

Violation → **IMMEDIATE STOP**.

---

## 6. Failure Handling

On **any** error or ambiguity:

- Stop immediately
- Report clearly
- Await human instruction

No retries. No fixes. No continuation.

---

## 7. Decision Rule (MEMORIZE THIS)

If you are unsure whether an action is allowed:

**Do not act. Stop and ask.**

---

**End of Trade_Scan Agent Execution Contract**
