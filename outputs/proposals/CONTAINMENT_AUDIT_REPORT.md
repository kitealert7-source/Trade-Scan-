# Agent Containment Audit (Mechanical Diagnostic)

## 1. Containment Controls Inventory

| Location | Trigger Condition | Enforcement Method | Type |
|---|---|---|---|
| `run_pipeline.py` | Stage completion | `check=True` on `subprocess.run` | Mechanical |
| `run_pipeline.py` | Run State entry | `run_state.json` forward-only transitions | Mechanical |
| `preflight.py` | Any execution start | Mandatory subprocess return code check (0 = ALLOW) | Mechanical |
| `verify_engine_integrity.py` | Preflight Stage | SHA-256 hash comparison against `vX_Y_Z/engine_manifest.json` | Mechanical |
| `semantic_validator.py` | Stage-0.5 | AST-based `BehavioralGuard` (FilterStack enforcement) | Mechanical |
| `semantic_validator.py` | Stage-0.5 | AST-based `HollowDetector` (Admission Gate) | Mechanical |
| `directive_schema.py` | Provision/Validation | `normalize_signature()` single-authority logic | Mechanical |
| `FilterStack.py` | Every `allow_trade` call | Runtime signature mutation check (SHA-256) | Mechanical |
| `FilterStack.py` | Every `allow_trade` call | `ctx.require(field)` authoritative field enforcement | Mechanical |
| `AGENT.md` | Playbook Reference | Systematic Invariants (1-13) | Procedural |
| `execute-directives.md` | Workflow start | Mandatory SOP ingestion and Step 1.5 Classification | Procedural |

---

## 2. Failure Surface Mapping

| Trigger | Current Response | Risk Level |
|---|---|---|
| Strategy logic gap | `HollowDetector` halts pipeline; reports `PROVISION_REQUIRED` | Low |
| Manual Strategy edit | `semantic_validator` signature mismatch halts execution | Low |
| Engine core modification | `verify_engine_integrity` hash mismatch blocks Preflight | Low |
| Governance document deletion | `preflight.py` reports `HARD_STOP` | Low |
| `--force` flag usage | Resets `run_state.json` to `INITIALIZED` (full rerun) | **Medium** |
| `workspace` mode usage | Skips engine hash verification | **Medium** |
| Agent modifying `tools/` | Proceeded by manual audit only (Protected Infrastructure) | **High** |

---

## 3. Authority Boundary Audit

### Strategy Authority

- **Crossing technically possible?** Yes (Agent can edit `.py` directly).
- **Prevention mechanism:** `semantic_validator.py` signature match + admission gate.
- **Is prevention structural or convention-based?** Structural (Mechanical Gate).

### Engine Authority

- **Crossing technically possible?** Yes (Agent can edit folder content).
- **Prevention mechanism:** `verify_engine_integrity.py` hash manifest.
- **Is prevention structural or convention-based?** Structural (Mechanical Gate).

### Governance Authority

- **Crossing technically possible?** Yes (Agent can edit SOPs).
- **Prevention mechanism:** `preflight.py` existence/size check.
- **Is prevention structural or convention-based?** Structural (Mechanical Gate).

### Workflow Authority

- **Crossing technically possible?** Yes (Agent can deviate from `.md` steps).
- **Prevention mechanism:** None (Requires manual inspection of logs).
- **Is prevention structural or convention-based?** Convention-based (Procedural).

---

## 4. Completion Bias Analysis

| Pattern | Detected Code Path / Behavior | Action taken |
|---|---|---|
| Auto-Recovery | None detected | All failures trigger `raise` or `sys.exit(1)` |
| Implicit Fixes | `strategy_provisioner.py` (Shell extraction) | Limited to structural provisioning only |
| Retry Loops | `run_pipeline.py` `--all` loop | Halts entire batch if single directive fails |
| Error Suppression | `plot_equity_curve` (matplotlib skip) | Converts to `[WARN]` (Non-authoritative output only) |
| Hard → Warn Conversion | `semantic_validator` (literal_eval fail) | Issue: Continues with `signature_dict = None` (potential gap) |

---

## 5. Containment Integrity Score

- **Escalation Resistance:** 9/10 (Strict stage gating prevents phase-skipping)
- **Mutation Resistance:** 8/10 (Hash checks protect engine, but `tools/` lack mechanical hashes)
- **Governance Enforcement Strictness:** 10/10 (Mandatory preflight gate is inescapable)
- **Immutability Guarantees:** 9/10 (Snapshotting and hash-binding secure execution history)

### Summary Findings

- **Strongest existing containment mechanism:** `verify_engine_integrity.py` SHA-256 enforcement. It creates a secondary cryptographic floor beneath the procedural rules.
- **Weakest containment gap:** `tools/` directory lack of mechanical manifest. While governed by "Protected Infrastructure" (procedural), the agent technically has mutation authority over the validator that guards the gate.
- **Highest-risk failure vector:** `run_pipeline.py --force`. While intended for recovery, it provides a mechanical "reset button" that can be used to repeatedly attempt mutated configurations without a separate audit trail for the reset event itself.

**Status:** Containment is structurally dominant for Execution/Engine, but procedurally reliant for Tools/Workflow authoring.
