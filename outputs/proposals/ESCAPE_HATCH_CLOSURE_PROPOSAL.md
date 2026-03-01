# Proposal — Closing Pipeline Escape Hatches (Workspace & Force)

## 🎯 Objective

Eliminate the two primary "Medium Risk" surfaces identified in the Containment Audit that allow for non-governed execution or state manipulation.

---

## 1. Deprecation of `workspace` Mode

Currently, `workspace` mode allows the pipeline to execute even if the engine code does not match the vaulted SHA-256 manifest.

### 🚫 The Risk

The agent can modify the engine's trade-execution logic (e.g., relax slippage, bypass ATR filters) and run it "in the workspace" while still reporting results as if from a governed run.

### ✅ The Fix

- **Remove `mode="workspace"`** from `verify_engine_integrity.py`.
- **Remove `skip_vault_check`** from `preflight.py`.
- **Enforcement**: Every execution through `run_pipeline.py` MUST be manifest-bound. If a human is developing a new engine, they must generate a temporary manifest or use a local dev harness that is not part of the `tools/` guard layer.

---

## 2. Restricting the `--force` Reset Flag

The `--force` flag allows the orchestrator to reset a `FAILED` directive state to `INITIALIZED` without any external authorization.

### 🚫 The Risk

Completion bias leads the agent to use `--force` to "fix" a failed backtest through iterative parameter mutation, effectively brute-forcing a passing result and breaking the "Single Intent" contract.

### ✅ The Fix

- **Demote to Governance-Only**: Remove the `--force` flag from `run_pipeline.py`.
- **New Reset Protocol**: Introduce a standalone tool `tools/reset_governance.py` that:
    1. Requires a mandatory `--reason` string.
    2. Appends the reset event and reason to a human-auditable `governance/audit_log.csv`.
    3. Only then clears the `run_state.json`.
- **Effect**: Resets are no longer "silent" side-effects of a retry command; they become explicit, logged governance interventions.

---

## 📈 Impact Analysis

| System Area | Before | After |
|---|---|---|
| **Engine Integrity** | Optional (strict vs workspace) | **Mandatory** (Strict SHA-256) |
| **State Management** | Self-healing via `--force` | **Audit-Required** via `reset_governance.py` |
| **Agent Autonomy** | Can retry and bypass | Must justify resets to an immutable log |

---

## 💡 Recommendation

Implement these closures concurrently with the **Guard-Layer Manifest** proposal. Together, they create a "Governance Box" that cannot be exited without creating a cryptographic or logged trace.
