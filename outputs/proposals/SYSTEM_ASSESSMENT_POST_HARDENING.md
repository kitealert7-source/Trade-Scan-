# System Assessment — Post-Governance Hardening

## Strengths Observed (Live Pipeline Run)

### 1. Root-of-Trust Chain — STRONG ✅

The vault-anchored hash check fired **before** any other gate. When the engine manifest was stale, the system hard-stopped. It did not attempt recovery, did not guess, did not proceed. This is the single most important behavior.

### 2. Schema V2 Rejection — STRONG ✅

Flat YAML was immediately rejected: `'test:' wrapper block is required`. No fallback parsing, no silent coercion. The directive was dead on arrival until restructured.

### 3. Ledger Supremacy — STRONG ✅

Stage-4 refused to overwrite an existing `SPX02_MR` entry in the Master Portfolio Sheet. This is the append-only guarantee working mechanically, not procedurally. Required explicit human deletion.

### 4. Reset Audit Trail — STRONG ✅

Five resets were performed during the run. Every one was logged to `governance/reset_audit_log.csv` with timestamp, directive ID, previous state, new state, and human-provided reason. The agent could not reset silently.

### 5. Dry-Run with Real ContextView — STRONG ✅

After the fix, the validator uses the exact same `ContextView` type as the engine runtime. FilterStack's governance guard passed with real objects, not mocks. Contract symmetry is restored.

### 6. Guard-Layer Manifest — MODERATE ✅

12 critical tools are SHA-256 bound. Missing manifest = hard fail. But this is only as strong as the human re-signing discipline (see Weaknesses).

---

## Weaknesses Identified

### 1. Directive Ping-Pong (active ↔ completed) — HIGH FRICTION ⚠️

**Problem:** `--provision-only` moves the directive to `completed/` even though the pipeline hasn't actually executed. This forces the human to manually move it back for full execution. During this run, the directive was moved **3 times** between `active/` and `completed/`.

**Root Cause:** The batch harness (`run_batch_mode`) unconditionally moves to `completed/` on success, but `--provision-only` counts as "success" even though it's only a validation step.

**Fix Required:** `--provision-only` should NOT move the directive to `completed/`. The move should only happen after `PORTFOLIO_COMPLETE`.

### 2. Run-Level State Orphaning — MEDIUM ⚠️

**Problem:** `reset_directive.py` resets the _directive-level_ state but does not clean per-symbol _run-level_ states. This caused the Stage-1 `State Mismatch` error (run was `IDLE` but Stage-1 expected `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`).

**Root Cause:** Directive state and run state live in separate files. The reset tool only knows about directive state.

**Fix Required:** `reset_directive.py` should also reset or archive associated run states under `runs/<RUN_ID>/run_state.json` for the directive's symbols.

### 3. Re-Execution Overhead — LOW ⚠️

**Problem:** After a Stage-4 failure (ledger conflict), the pipeline re-ran Stages 0-3 from scratch instead of resuming at Stage-4. The individual run was already `COMPLETE`, but the directive reset pushed everything back to `INITIALIZED`.

**Root Cause:** The reset tool only supports `FAILED → INITIALIZED`. There is no `FAILED → SYMBOL_RUNS_COMPLETE` transition for Stage-4-only retries.

**Possible Fix:** Add a `--resume-stage4` flag to the reset tool that sets directive state to `SYMBOL_RUNS_COMPLETE` instead of `INITIALIZED`, preserving completed run artifacts.

### 4. Vault is Procedurally Protected — ACKNOWLEDGED ⚠️

As discussed: the agent has write access to `vault/`. The root-of-trust is procedurally enforced (AGENT.md invariant #17), not mechanically. This is a known limitation of single-user local systems. Mitigation: human reviews all agent commands before execution.

### 5. Engine Manifest Staleness — LOW ⚠️

The engine manifest was stale (2 files changed since last signing). This was correctly caught, but it required manual hash recomputation. There is no `generate_engine_manifest.py` equivalent to `generate_guard_manifest.py`.

---

## Overall System Rating

| Dimension | Score | Notes |
|---|---|---|
| **Integrity Enforcement** | 9/10 | Root-of-trust + engine + tools manifests form a closed verification chain |
| **Fail-Fast Discipline** | 9/10 | Every failure results in immediate halt. No silent recovery |
| **Audit Trail** | 8/10 | Reset logging works. Missing: manifest re-signing audit |
| **State Management** | 6/10 | Directive/run state split causes orphaning. Reset is too coarse |
| **Operational Ergonomics** | 5/10 | Directive ping-pong, manual moves, full re-execution on Stage-4 retry |
| **Vault Security** | 4/10 | Procedural only. Agent has write access. Human is the gate |

### **Composite Score: 7/10**

> The system's _detection_ and _enforcement_ capabilities are strong. It catches violations reliably and halts correctly. The weaknesses are in _operational friction_ (too many manual steps, state orphaning) and _vault protection_ (procedural, not mechanical). The containment box is structurally sound against accidental violations but relies on human vigilance against intentional ones.

---

## Recommended Priority Fixes

| Priority | Fix | Effort |
|---|---|---|
| **P0** | `--provision-only` should not move directive to `completed/` | 5 lines |
| **P1** | `reset_directive.py` should clean associated run states | 20 lines |
| **P2** | Add `generate_engine_manifest.py` (mirror of guard manifest tool) | New file |
| **P3** | Stage-4 retry without full re-execution | Design needed |
