# SOP_AGENT_ENGINE_GOVERNANCE

**Status:** AUTHORITATIVE | ENFORCEMENT  
**Applies to:** All AI agents modifying or proposing changes to Trade_Scan engines  
**Precedence:**  
Trade_Scan_invariants  
→ SOP_TESTING / SOP_OUTPUT  
→ SOP_AGENT_ENGINE_GOVERNANCE  
→ Agent Rules  
→ Agents

---

## 1. Purpose

This document governs **how engines may be created, modified, validated, and promoted** within Trade_Scan.

It exists to:
- prevent silent engine drift
- protect proven engines
- preserve reproducibility
- enforce deliberate engine evolution

This SOP is **prohibitive by default**.

---

## 2. Engine Classification (MANDATORY)

Every engine exists in **exactly one** of the following states.

### 2.1 Experimental Engine
- Location: `engine_dev/`
- Mutable
- Not trusted
- No reproducibility guarantees
- May be modified **only with explicit human instruction**

### 2.2 Validated / Released Engine
- Location: `engine_registry/releases/<engine_type>/<version>/`
- Identified by:
  - `VALIDATED_ENGINE.manifest.json`
  - file hashes
  - registry entry
- **Immutable**
- Used for authoritative runs

### 2.3 Deprecated Engine
- No longer recommended
- Remains immutable
- Retained for historical reproducibility

---

## 3. Core Immutability Rule (HARD)

**Any engine that has a `VALIDATED_ENGINE.manifest.json` and appears in `registry_index.json` MUST NOT be modified.**

- No bug fixes
- No refactors
- No logging additions
- No performance optimizations
- No formatting changes

An engine becomes immutable immediately after its first RUN_COMPLETE execution
using that engine version.
Validated engines MUST NOT be deleted, renamed, or structurally reorganized.

**Any change creates a new engine.**

---
### 3.1 Vaulted Engines (ENFORCEMENT)

Validated engines may be physically isolated into a vault structure for preservation.

Vaulting:
- does NOT change engine identity
- does NOT modify code, manifests, or hashes
- is a storage and governance action only

Vaulted engines remain subject to all immutability and reproducibility rules
defined in this SOP.

## 4. Agent Authorization to Modify Code

Agents MAY modify engine code **only if all conditions are met**:

1. A human explicitly authorizes a change
2. The change scope is declared
3. The engine is located under `engine_dev/`
4. The engine is **not** registered or validated

If **any condition fails**, the agent MUST stop and ask.

---

## 5. Change Classification (MANDATORY STEP)

Before writing code, agents MUST classify the request:

### 5.1 Research / Analysis
- Conceptual metrics
- Explanations
- Hypotheses

➡️ No code changes allowed

---

### 5.2 New Run Using Existing Engine
- Parameter changes
- Different directives
- New date ranges

➡️ No engine changes allowed

---

### 5.3 Engine Evolution
- New metric requiring new computation
- Logic changes
- Execution behavior changes
- Bug fixes

Successor engines SHOULD record their base engine (engine_type + version)
in the VALIDATED_ENGINE.manifest.json under a `base_engine` field
to preserve lineage and traceability.




➡️ Requires a new engine

Agents MUST explicitly state this classification before proceeding.
When a request is classified as Engine Evolution, agents MUST follow this flow exactly.

Engine Evolution includes:
- creating a successor to an existing engine, OR
- creating a brand-new engine to test a completely new hypothesis.

Before implementing a new engine or a successor engine, agents MUST:

1. Acknowledge review of the following governing documents:
   - Trade_Scan_invariants
   - SOP_TESTING
   - SOP_OUTPUT
   - SOP_AGENT_ENGINE_GOVERNANCE

2. Explicitly confirm:
   - No validated engine will be modified
   - Execution semantics changes (if any) are declared
   - All emitted artifacts remain compliant with SOP_TESTING and SOP_OUTPUT
   - Reproducibility of prior runs is preserved

Agents MUST state this confirmation explicitly before writing any code.


1. Declare intent:
   - State whether this is:
     a) a successor engine, or
     b) a brand-new hypothesis engine
   - If successor: identify the base engine (type + version)
   - If brand-new: state the hypothesis being tested in one sentence

2. Propose identity:
   - Propose a new engine type and/or version
   - Confirm that no validated engine will be modified

3. Establish engine location:
   - If successor engine:
     copy ONLY from:
       engine_registry/releases/<engine_type>/<version>/
   - If brand-new hypothesis engine:
     create a new directory under:
       engine_dev/<new_engine_type>/<version>/

4. Implement changes:
   - Modify ONLY code under engine_dev/
   - Make minimal, scoped changes aligned to the declared hypothesis
   - Do not touch engine_registry, manifests, or registry index

5. Declare impact:
   - Explicitly state whether execution semantics changed
   - Explicitly list new or modified metrics (if any)

Agents MUST NOT proceed to implementation until steps 1–3 are completed and acknowledged.

---

## 6. Forking Protocol (MANDATORY)

When engine evolution is approved:

1. Copy the base engine from:
   `engine_registry/releases/<engine_type>/<version>/`
   to:
   `engine_dev/<engine_type>/<new_version>/`

2. Modify **only** the forked copy  
3. Do not reference or patch the original  
4. Treat the fork as a new engine identity  

---

## 7. Delivery Rules for Code Changes

Agents MUST:
- make minimal, scoped changes
- avoid refactors unless explicitly requested
- deliver **full replacement blocks**
- state clearly:
  - what changed
  - what did NOT change
  - whether execution semantics changed

Agents MUST NOT:
- change defaults silently
- modify multiple engines unless instructed
- merge changes back into validated engines

---

## 8. Validation & Promotion

An engine may be promoted **only by humans**.

Promotion requires:
- successful runs
- validation review
- creation of `VALIDATED_ENGINE.manifest.json`
- registry entry update

Agents MAY assist but MUST NOT self-promote engines.

---

## 9. Provenance & Reproducibility Rule

All historical runs must remain reproducible using the exact engine version recorded at execution time.

Any action that breaks this rule is a **system violation**.

---

## 10. Violation Handling

If an agent:
- modifies a validated engine
- bypasses the registry
- mutates engine code without authorization

The action MUST:
- abort immediately
- be disclosed
- require corrective human instruction

---

## Final Rule

If a requested change:
- alters execution truth
- changes computed metrics
- affects economic outcomes

Then it is **engine evolution**, not a small change.

---

**End of SOP_AGENT_ENGINE_GOVERNANCE**
