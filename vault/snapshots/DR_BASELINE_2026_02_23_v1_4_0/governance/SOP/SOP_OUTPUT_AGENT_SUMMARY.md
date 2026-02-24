# SOP_OUTPUT — Agent Summary (ENFORCEMENT)

Status: ACTIVE  
Audience: All agents participating in Trade_Scan runs
This file is the ONLY agent-facing summary for SOP_OUTPUT.
Agents must not interpret SOP_OUTPUT.md directly.

This document summarizes the ONLY rules agents must follow
when handling results emission and analysis.

Authoritative definitions remain in SOP_OUTPUT.md.
If conflict exists, SOP_OUTPUT.md overrides this summary.

---

## 1. Stage Ownership (NON-NEGOTIABLE)

- Stage-1 computes ALL metrics.
- Stage-2 operates Stage-1 outputs only.
- Stage-3 aggregates from Stage-1 and Stage-2 artifacts.

Agents MUST NOT compute, infer, or recompute metrics
outside Stage-1.

---

## 2. One-Way Flow (HARD)

Flow is strictly:

Stage-1 → Stage-2 → Stage-3 → Stage-3A (Strategy Snapshot Finalization) → Stage-4 (Portfolio Analysis) → Human

Stage-3A is part of run finalization and is governed by SOP_OUTPUT.

Stage-4 is governed exclusively by SOP_PORTFOLIO_ANALYSIS.

Backflow is forbidden.

---

## 3. Artifact Rules

Agents MUST:

- treat Stage-1 artifacts as immutable
- treat Stage-2 artifacts as read-only
- append only; never mutate existing artifacts

Agents MUST NOT:

- edit CSVs
- edit Excel reports
- “fix” numbers
- regenerate metrics

---

## 4. RUN_COMPLETE Gate

Agents MAY act only if:
run_status == RUN_COMPLETE

RUN_COMPLETE is defined as successful completion of:

Stage-1 → Stage-2 → Stage-3 → Stage-3A (Strategy Snapshot Finalization)

A run without a valid strategy snapshot
is NOT considered complete.

Failed or partial runs do not exist.

Agents MUST assume all pre-existing artifacts for the same strategy
belong to a superseded run and MUST NOT reuse, merge, or reason across runs.

Agents MUST follow SOP_OUTPUT.md as the authoritative source.

---

## 5. Stage-5 Strategy Persistence (POST-RUN INVARIANT)

For every folder present under:

    backtests/<strategy_name>/

the system MUST have:
    - a strategy snapshot under strategies/<DirectiveName>/, AND
    - an immutable engine snapshot under runs/<RUN_ID>/ (if applicable).

---

## 6. Failure Handling

On any ambiguity or error:

- STOP
- REPORT
- WAIT for human instruction

No retries. No silent continuation.

---

End of SOP_OUTPUT Agent Summary
