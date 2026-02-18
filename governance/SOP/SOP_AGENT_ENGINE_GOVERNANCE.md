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

- Canonical identity: `engine_dev/<engine_type>/<version>/` (physical storage may be vaulted)
- Identified by:
  - `VALIDATED_ENGINE.manifest.json`
  - file hashes
- **Immutable**
- Used for authoritative runs

### 2.3 Deprecated Engine

- No longer recommended
- Remains immutable
- Retained for historical reproducibility

---

## 3. Core Immutability Rule (HARD)

**Any engine that has a `VALIDATED_ENGINE.manifest.json` MUST NOT be modified.**

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
     copy from:
       `engine_dev/<engine_type>/<version>/`
   - If brand-new hypothesis engine:
     create a new directory under:
       `engine_dev/<new_engine_type>/<version>/`

4. Implement changes:
   - Modify ONLY code under engine_dev/
   - Make minimal, scoped changes aligned to the declared hypothesis
   - Do not touch validated manifests

5. Declare impact:
   - Explicitly state whether execution semantics changed
   - Explicitly list new or modified metrics (if any)

Agents MUST NOT proceed to implementation until steps 1–3 are completed and acknowledged.

---

## 6. Forking Protocol (MANDATORY)

When engine evolution is approved:

1. Copy the base engine from:
   `engine_dev/<engine_type>/<version>/`
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

## 11. Strategy Staging, Snapshot & Directive Artifact Governance (MANDATORY)

This section governs the interaction between:

- Development Environment (mutable strategy staging)
- Execution Pipeline
- Directive Artifact Store (immutable results)

This protocol applies to all strategy-based backtests executed via the pipeline.

---

### 11.1 Staging Principle (Execution Source of Truth)

For strategy-based runs, the folder:

```text
strategies/<StrategyFamily>/
```

acts as the **Staging Engine**.

It is:

- Mutable
- The single source of truth for execution
- Loaded directly by the pipeline
- Considered LOCKED during execution

The pipeline does NOT execute from directive folders.
It executes only from the staging folder.

---

### 11.2 Directive Execution Rule

When a directive specifies:

```text
Strategy: <StrategyFamily>
```

The pipeline MUST load:

```text
strategies/<StrategyFamily>/strategy.py
```

Requirements:

- The staging engine MUST be fully prepared before execution.
- The staging engine MUST NOT be modified during execution.
- Any mid-run mutation constitutes a governance violation.

---

### 11.3 Mandatory Snapshot Creation (NON-OPTIONAL)

Immediately after a successful RUN_COMPLETE status:

The exact staged engine used MUST be snapshotted into the directive artifact folder.

Required structure:

```text
strategies/<DirectiveName>/
    strategy.py
    STRATEGY_SNAPSHOT.manifest.json
```

The snapshot MUST include:

1. A byte-identical copy of:

    ```text
    strategies/<StrategyFamily>/strategy.py
    ```

2. A manifest file containing:
   - sha256 hash of strategy.py
   - timestamp (UTC)
   - directive name
   - strategy family name
   - pipeline run identifier (if available)
   - dependency engine versions (if applicable)

Failure to create this snapshot invalidates reproducibility guarantees.

---

### 11.4 Snapshot Immutability Rule

Once created, the folder:

```text
strategies/<DirectiveName>/
```

is classified as an **Immutable Historical Artifact**.

The following are strictly prohibited:

- Modifying strategy.py inside the directive folder
- Regenerating or editing the snapshot manifest
- Deleting snapshot files
- Renaming directive artifact folders

Any such action is treated as equivalent to modifying a validated engine
and falls under Section 10 (Violation Handling).

---

### 11.5 Relationship to engine_dev Governance

This protocol:

- Does NOT override Section 3 (Core Immutability Rule)
- Does NOT permit modification of validated engines under engine_dev/
- Applies only to strategy staging folders

If a strategy depends on a validated engine:

Engine immutability rules remain in full force.

---

### 11.6 Strategy Evolution Rule

If a staged strategy change alters:

- Execution semantics
- Trade logic
- Risk model
- Economic outcomes
- Computed metrics

Then it constitutes strategy evolution and MUST:

- Be executed under a new directive name
- Produce a new snapshot
- Preserve all prior directive artifacts unchanged

Overwriting or reusing directive folders is prohibited.

---

### 11.7 Enforcement Principle

Reproducibility is defined as:

```text
Historical results + Exact strategy snapshot + Dependency identity
```

If any of the above cannot be reconstructed deterministically,
the system is considered in violation.

This rule is non-negotiable.

### 11.8 Pipeline Enforcement Requirement (MANDATORY)

The execution pipeline MUST automatically generate the required
strategy snapshot and manifest defined in Section 11.3
upon successful RUN_COMPLETE status.

Manual snapshotting is prohibited.

The pipeline MUST:

- Copy the staged strategy.py into the directive artifact folder
- Generate STRATEGY_SNAPSHOT.manifest.json
- Compute and store sha256 hash
- Abort completion if snapshot generation fails

A run is not considered complete unless snapshot creation succeeds.

Any pipeline implementation that omits this enforcement
is non-compliant with this SOP.

## Final Rule

If a requested change:

- alters execution truth
- changes computed metrics
- affects economic outcomes

Then it is **engine evolution**, not a small change.

---

**End of SOP_AGENT_ENGINE_GOVERNANCE**
