# Engine Vault Contract — Universal Research Engine (Embedded Model)

Engine: Universal_Research_Engine  
System: Trade Scan  
Canonical Source Location:
`engine_dev/universal_research_engine/<version>/`

Vault Location:
`vault/engines/Universal_Research_Engine/<version>/`

Purpose:
Disaster recovery, audit replay, and immutable backup only.

The Vault exists to protect the system — not to operate it.

---

## 1. Core Principle

The engine lives inside the Trade Scan system.

The Vault is a read-only mirror of a validated engine version.

The system runs from engine_dev.
The Vault never participates in execution.

Vault = safety net.
System = operational authority.

---

## 2. Canonical Authority

Authoritative engine state is defined by:

`engine_dev/universal_research_engine/<version>/`

Only this directory is used for:

- Execution
- Testing
- Preflight
- Strategy runs
- Portfolio evaluation

Vault contents must never be imported into runtime.

---

## 3. Vault Invariants (Must Never Be Violated)

1. Vault contents are immutable after promotion.
2. No file inside a vaulted version may be edited.
3. No runtime artifacts may exist inside vault.
4. Vault must reflect a clean committed system state.
5. Vault versions must match system engine version exactly.

If corruption occurs:

- Do not patch in place.
- Invalidate and promote a new version.

---

## 4. Promotion Workflow

Promotion occurs only after:

1. Engine validated inside system.
2. Preflight PASS.
3. Full pipeline PASS.
4. Governance checks PASS.
5. Git working tree clean.

Then:

1. Generate engine manifest from canonical source.
2. Copy `engine_dev/universal_research_engine/<version>/`
   → `vault/engines/Universal_Research_Engine/<version>/`
3. Commit vault snapshot.
4. Tag version.
5. Never modify that version again.

Vault creation is a snapshot event — not a development step.

---

## 5. What Vault Is NOT

Vault is NOT:

- An execution selector.
- A runtime dependency.
- A strategy container.
- A portfolio store.
- A development workspace.
- A place for results, logs, or artifacts.

If it changes system behavior, it is misused.

---

## 6. Manifest Rule

Each vaulted version must contain:

manifests/engine_manifest.json

Manifest must:

- Be generated from canonical system engine.
- Reflect file hashes at time of promotion.
- Be tied to system commit hash.
- Not be manually edited.

Manifest exists for audit, replay, and forensic validation.

---

## 7. Version Discipline

Any change to:

- Stage-1 logic
- Stage-2 logic
- Stage-3 logic
- Governance logic
- Integrity verification logic

Requires:

- New engine version directory
- New vault promotion
- New tag

Vault versions are historical evidence.

---

## 8. Disaster Recovery Model

If system becomes corrupted:

1. Identify last valid vaulted version.
2. Restore that version into engine_dev.
3. Re-run integrity verification.
4. Resume operations.

Vault protects against:

- Accidental deletion
- Corrupted commits
- Broken refactors
- Environment failure

Vault does not control live execution.

---

## 9. Operational Separation

Daily operations occur exclusively in:

engine_dev/universal_research_engine/

Vault remains untouched unless:

- Promoting a new validated version
- Restoring after failure
- Auditing historical behavior

If vault is touched during daily development, process is broken.

---

## 10. Agent Access Restriction

Autonomous agents must NOT:

- Read
- Audit
- Validate
- Import
- Reference
- Or open any Vault directory

Unless explicitly directed by a human instruction that clearly authorizes Vault access.
Vault access is opt-in, never automatic.
By default, all agents operate exclusively on the canonical system engine inside:

engine_dev/universal_research_engine/

Any automatic Vault inspection, validation, or integrity enforcement during normal execution is a contract violation.

Vault is not part of day-to-day functioning.
The system must operate fully and independently without requiring any interaction with the Vault.
If normal execution depends on Vault access, the architecture is considered broken.

---

This contract defines the separation between
Operational Engine and Archival Evidence.

The system runs forward.
The Vault protects history.
