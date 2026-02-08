# Engine Vault Contract — Universal Research Engine

**Engine:** Universal_Research_Engine v1.1.0  
**Vault Location:** `vault/engines/Universal_Research_Engine/v1.1.0/`  
**Purpose:** Archival / safekeeping only

---

## 1. Vault Invariants (MUST NEVER CHANGE)

- Vault contents are immutable snapshots.
- No file inside a vaulted version may be edited.
- Any change to engine code, stage logic, or SOPs requires a new engine version.

Vault = evidence, not workspace.

---

## 2. Authority Boundaries

- **Stage-1**: Executes strategy logic and emits authoritative artifacts only.
- **Stage-2**: Consumes Stage-1 artifacts; presentation only; no inference.
- **Stage-3**: Performs master strategy filtering / aggregation only.
- **SOPs**: Define governance and constraints; engines must obey them.

No stage may recompute or override another stage’s authority.

---

## 3. Capital & Governance Contract

- Capital is broker-spec authoritative.
- No silent defaults anywhere.
- Governance gate must pass before Stage-2 / Stage-3.
- Buy & Hold is contextual-only (never ranked or enforced).

These rules are frozen for this engine version.

---

## 4. Promotion Workflow (FOR FUTURE UPDATES)

1. Develop changes outside the vault.
2. Verify SOP alignment.
3. Audit Stage-1, Stage-2, Stage-3 engines.
4. Promote to:
   `vault/engines/Universal_Research_Engine/vX.Y.Z/`
5. Generate hashes and manifest.
6. Never modify prior versions.

---

## 5. What This Vault Is NOT

- Not an execution selector.
- Not a policy enforcer.
- Not strategy-specific.
- Not a mutable codebase.

This vault exists for audit, replay, and rollback only.

---

## 6. Reference Artifact

The file `manifests/engine_manifest.json` is the single source of truth for this engine version.
