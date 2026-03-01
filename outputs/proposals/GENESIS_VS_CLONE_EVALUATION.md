# Evaluation — Genesis vs Clone Strategy Policy

## 1. Architectural Impact

### Does this reduce hidden state?

**Yes — significantly.** The primary hidden state in the current system is *implicit behavioral inheritance*. When a new strategy is created by referencing or borrowing from an existing one, the following are invisible:

- Which parts were borrowed vs authored fresh
- Whether borrowed logic is semantically compatible with the new directive
- Whether the agent adapted engine infrastructure to accommodate mismatches

GENESIS_MODE eliminates all three. The strategy's provenance is unambiguous: directive → implementation, no intermediaries.

CLONE_MODE makes the inheritance explicit: the file already exists, so modification history is tracked via version control.

### Does this improve determinism?

**Yes.** Currently, strategy generation is non-deterministic in the meta sense — the *same directive* processed at different times might produce different strategy code depending on which other strategies the agent found and borrowed from. GENESIS_MODE forces a single deterministic input (the directive) to single deterministic output (the strategy).

### Does this conflict with any current pipeline stages?

**No conflicts.** The policy operates entirely *before* Stage-0 (Preflight). It governs strategy *authoring*, not execution. The pipeline stages are:

| Stage | Affected? | Reason |
|---|---|---|
| Provisioning | Compatible | Provisioner already generates skeleton; policy governs what fills it |
| Semantic Validation (0.5) | Compatible | Validates regardless of how strategy was authored |
| Coverage Gate (0.55) | Compatible | Static check, mode-agnostic |
| Dry-Run (0.75) | Compatible | Runtime structural check, mode-agnostic |
| Stage 1+ | Unaffected | Execution is mode-agnostic |

---

## 2. Failure Mode Analysis

### New failure modes this could introduce

| Failure Mode | Severity | Mitigation |
|---|---|---|
| GENESIS strategy takes longer to implement (agent must reason from scratch) | Low | Acceptable — correctness > speed |
| GENESIS strategy may have implementation gaps the agent can't fill from directive alone | Medium | Already caught by Coverage Gate (0.55) + Admission Gate (Step 3) |
| CLONE_MODE may overwrite user-authored changes if provisioner re-generates | Low | Already mitigated by signature comparison — provisioner skips if unchanged |

### Could this block legitimate reuse patterns?

**Partially — but this is intentional.** The policy explicitly blocks:

- Cross-family logic reuse (e.g. borrowing ORB entry logic for a mean-reversion strategy)
- Adaptive borrowing of behavioral blocks from unrelated strategies

These are the exact patterns that caused the SPX02_MR cascade. Blocking them is the *goal*.

**Legitimate reuse that remains allowed:**

- Structural template reuse (class skeleton, method signatures) — explicitly permitted in GENESIS_MODE
- Full file reuse via CLONE_MODE when the strategy already exists

### Could this increase friction unnecessarily?

**Marginally.** GENESIS_MODE strategies may require more explicit directive parameters since the agent cannot infer intent from similar strategies. However, this friction is *useful* — it forces directives to be self-contained, which improves reproducibility.

---

## 3. Interaction with Existing Systems

### Signature Unification (v2)

**Fully compatible.** `normalize_signature()` operates on the directive YAML, not on strategy code. The generation mode does not affect signature construction. Both GENESIS and CLONE strategies will have identical signature validation paths.

### Semantic Coverage Gate (Stage 0.55)

**Strengthened.** GENESIS_MODE + Coverage Gate creates a two-layer safety net:

1. GENESIS forces the agent to implement from directive parameters only
2. Coverage Gate verifies every declared parameter is actually referenced

Together, they eliminate the gap where borrowed logic *accidentally satisfies* coverage by referencing parameters it doesn't actually use correctly.

### Admission Gate (Step 3)

**Unchanged.** Human review applies regardless of generation mode. The mode simply affects *what the human is reviewing* — a from-scratch implementation (GENESIS) vs a modification of existing code (CLONE).

### Protected Infrastructure Policy

**Reinforced.** The GENESIS_MODE rule "Must NOT patch engine infrastructure to accommodate strategy" is a direct restatement of the Protected Infrastructure Policy applied to the generation phase. They are complementary, not conflicting.

---

## 4. Minimal Implementation Path

### Where should this rule be enforced?

| Layer | Enforcement | Justification |
|---|---|---|
| **Workflow** (primary) | ✅ Yes | Cheapest, most visible, easiest to audit |
| Strategy generation layer | ⚠️ Informational only | Log the mode, don't gate on it programmatically |
| `run_pipeline.py` | ❌ No | Pipeline should not care how strategy was authored |

**Recommendation: Workflow-level enforcement only.**

The `/execute-directives` workflow already has the Admission Gate (Step 3). The mode detection is a pre-Step-2 classification that guides *agent behavior*, not a runtime gate.

### Smallest safe enforcement mechanism

Add to `/execute-directives.md` between Step 1 and Step 2:

```
### Step 1.5: Strategy Generation Mode Classification

Before provisioning, classify each directive:

- If `strategies/<STRATEGY_NAME>/strategy.py` EXISTS → CLONE_MODE
  - Log: "[MODE] CLONE_MODE: Existing strategy found"
  - Modifications to existing code are permitted
  - Must pass semantic coverage gate after changes

- If `strategies/<STRATEGY_NAME>/strategy.py` DOES NOT EXIST → GENESIS_MODE
  - Log: "[MODE] GENESIS_MODE: New strategy required"
  - Implement from directive parameters only
  - Do NOT search for or reference other strategy implementations
  - Do NOT borrow behavioral logic from other families
  - Structural template (class skeleton, method signatures) may be consulted
  - If implementation fails → halt and report. Do NOT patch engine.
```

This is ~15 lines added to an existing workflow file. No new runtime modes, no schema changes, no engine modifications.

---

## 5. Unintended Consequences

### Could this affect strategy refactors?

**No.** Refactoring an existing strategy is CLONE_MODE by definition (file already exists). The policy does not restrict modifications to existing files.

### Could this affect versioned engine snapshots?

**No.** The policy governs strategy *authoring*, not engine versioning. Snapshots are taken after provisioning, regardless of mode.

### Could this interfere with backtesting completed directives?

**No.** Completed directives already have strategies in `strategies/`. Re-running them would trigger CLONE_MODE, which permits the existing implementation. No behavioral change.

### Edge case: Strategy directory exists but `strategy.py` was deleted

This would trigger GENESIS_MODE (file does not exist), which is correct — the agent should implement from scratch rather than guessing what the deleted file contained.

---

## 6. Recommendation

### **GO** ✅

**Justification:**

1. Zero conflicts with existing infrastructure
2. Prevents the exact failure cascade observed in SPX02_MR
3. Enforceable at workflow level only — no engine changes needed
4. Compatible with signature unification v2, coverage gate, and Protected Infrastructure Policy
5. Does not block any legitimate pattern that should be preserved
6. Minimal implementation: ~15 lines in one workflow file

### Minimal Enforcement Outline

| Component | Change | Size |
|---|---|---|
| `.agents/workflows/execute-directives.md` | Add Step 1.5 (mode classification) | ~15 lines |
| `.agents/workflows/execute-directives.md` | Add mode to Step 5 failure reporting | ~3 lines |
| No new files | — | — |
| No engine changes | — | — |
| No schema changes | — | — |
| No runtime modes | — | — |
