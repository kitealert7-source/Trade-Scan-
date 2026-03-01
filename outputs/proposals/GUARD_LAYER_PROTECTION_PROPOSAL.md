# Proposal — Guard-Layer Mechanical Integrity

## 🎯 Problem Statement

The "Guard Layer" (`run_pipeline.py`, `semantic_validator.py`, `directive_schema.py`) is currently protected by **procedural agreement** (Protected Infrastructure Policy) but lacks **mechanical enforcement**. An agent can technically modify the validator to bypass a governance check and then restore the code, leaving no cryptographic trace of the bypass.

---

## 🛠️ Proposed Solution: The Tools-Guard Manifest

Move the `tools/` directory to a "Manifest-Bound" state, identical to the Engine.

### 1. Mechanical Manifest Construction

Create `tools/tools_manifest.json` which stores SHA-256 hashes of the **Critical Guard Set**:

- `run_pipeline.py` (Orchestrator)
- `semantic_validator.py` (Behavioral/Identity Guard)
- `directive_schema.py` (Signature Authority)
- `strategy_dryrun_validator.py` (Runtime Guard)
- `verify_engine_integrity.py` (Integrity Guard)
- `preflight.py` (Admission Gate)

### 2. Mandatory Preflight Activation

Update `tools/verify_engine_integrity.py` (or a dedicated `tools/verify_tools_integrity.py`) to:

- Load `tools/tools_manifest.json`.
- Fail hard if manifest is missing.
- Fail hard on any hash mismatch.
- **Bootstrapping**: This check must be the first line of `run_pipeline.py`. If the integrity script itself is modified, the hash of `verify_engine_integrity.py` stored in the manifest will fail (unless the agent also modifies the manifest).

### 3. Human-Signed Manifest Updates

To prevent the agent from silently updating the manifest after a bypass:

- **Manual Update only**: The agent is strictly forbidden from writing to `tools_manifest.json`.
- **Audit Procedure**: Any legitimate change to a tool requires a human to run a local script to re-generate the manifest, or provided by the human as a separate action.

---

## 🛡️ Authority Boundary Enforcement

| Authority | Current (Procedural) | Proposed (Mechanical) |
|---|---|---|
| **Pipeline Logic** | "I won't change it" | SHA-256 Manifest check in Preflight |
| **Logic Bypass** | "I will follow rules" | `semantic_validator.py` hash verified before run |
| **State Reset** | `run_pipeline.py --force` | Require human-provided `RESET_TOKEN` or separate CLI |

---

## 📈 Implementation Roadmap (Minimal Surface)

1. **Step A**: Identify 6-8 core files for the Critical Guard Set.
2. **Step B**: Populate `tools/tools_manifest.json`.
3. **Step C**: Activate `verify_tools_integrity()` in `preflight.py`.
4. **Step D**: Update `AGENT.md` to define "Manifest Tampering" as a `HARD_STOP` event requiring human intervention.

## ⚖️ Trade-offs

- **Increased Friction**: Every small improvement to `tools/` (like adding a logging statement) will require a manifest update.
- **Overhead**: Minor performance hit (milliseconds) during preflight to hash the toolset.
- **Benefit**: Absolute cryptographic guarantee that the validator running *right now* is the authoritative version approved by the human.

---

## 💡 Recommendation

**Proceed with Step A and B.** Creating the manifest is non-destructive and establishes the baseline. Step C (Mechanical Blocking) should be activated once the baseline is stable.
