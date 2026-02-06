# Trade_Scan — Workflow (FINAL)

## NOTE ON AUTHORITY (MANDATORY)

This document is **descriptive only**.

Authoritative system behavior is defined exclusively by:
- `Trade_Scan_invariants.md`
- `SOP_TESTING.md`
- `SOP_OUTPUT.md`

If any inconsistency exists between this workflow and the documents above, **this workflow is wrong**.

---

## 1. Purpose

This document describes the **complete end-to-end workflow** of Trade_Scan as it is used in practice.

Its role is to:
- provide a clear mental model for humans and agents
- explain sequencing without introducing authority
- show where Trade_Scan begins and where it ends

This document does **not** define rules, constraints, or decision rights.

---

## 2. Preconditions

Trade_Scan operates only when all of the following are true:

- A human has formulated a research question
- A corresponding research directive exists
- The directive is explicitly selected by a human

If these conditions are not met, Trade_Scan **does not run**.

---

## 3. Human Entry Point — Research Directive

1. A human creates, edits, or selects a research directive.
2. The directive represents the full declared intent for the run.
3. The directive is placed in the active directives location.

The directive is the **sole trigger** for any Trade_Scan activity.

Trade_Scan never initiates work on its own.

---

## 4. Research Execution — SOP_TESTING

When a human explicitly invokes Trade_Scan:

1. The selected directive is read.
2. The directive is validated for completeness and internal consistency.
3. Execution scope is constrained strictly to what the directive declares.
4. Research logic is executed.
5. Economic validation is applied using simulated capital and declared cost models.
6. All required artifacts are generated.

Execution is **atomic**.

Possible outcomes:
- **RUN_COMPLETE** — all declared work completed successfully
- **Failure** — execution aborted and no artifacts persist

Trade_Scan does not:
- retry automatically
- branch execution paths
- adapt based on interim results

---

## 5. Results Emission — SOP_OUTPUT

For runs marked RUN_COMPLETE:

1. Trade_Scan consumes authoritative execution artifacts.
2. Results are emitted exactly once.
3. Artifacts are produced in two forms:
   - Authoritative execution artifacts (execution truth)
   - Derived presentation artifacts for human review
4. All emitted artifacts are append-only and immutable.

Runs that are not RUN_COMPLETE are ignored entirely.


---

## 6. Human Analysis Phase

After results emission:

1. Humans review CLEAN reports.
2. Humans may explore RESEARCH artifacts.
3. Comparisons across runs may be performed.
4. Insights and hypotheses are formed externally.

All analysis performed at this stage is **advisory only**.

No conclusions, rankings, or judgments automatically influence future execution.

---

## 7. Stop or Iterate — Human Decision

After review, humans explicitly choose one of the following:

### Stop
- The directive is archived.
- No further work occurs under that directive.

### Iterate
- The directive is explicitly refined, extended, or amended by a human.
- A new run may occur only after such explicit change.

There is **no automatic loop-back** from results to execution.

Trade_Scan never decides to iterate.

---

## 8. System Boundary — Where Trade_Scan Ends

Trade_Scan ends after results emission and human review.

It does **not**:
- select strategies
- promote outcomes
- recommend deployment
- trigger further runs
- interact with execution or trading systems

Any next action is **human-initiated and external** to Trade_Scan.

---

## 9. End-to-End Summary

```
Human Research Question
        ↓
Human Directive
        ↓
SOP_TESTING (Execute & Validate)
        ↓
RUN_COMPLETE or Failure
        ↓
SOP_OUTPUT (Emit Results)
        ↓
Human Analysis
        ↓
Stop  |  Iterate (Human Decision)
```

---

**End of Trade_Scan Workflow (FINAL)**

