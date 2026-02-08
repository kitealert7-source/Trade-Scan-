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
- Stage-3 operates Stage-2 outputs only.

Agents MUST NOT compute, infer, or recompute metrics
outside Stage-1.

---

## 2. One-Way Flow (HARD)

Flow is strictly:

Stage-1 → Stage-2 → Stage-3 → Human

Backflow is forbidden.

---

## 3. Artifact Rules

Agents MUST:
- treat Stage-1 artifacts as immutable
- treat Stage-2 artifacts as read-only
- append only; never overwrite

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
Stage-1 → Stage-2 → Stage-3

Failed or partial runs do not exist.


---
## 5. Stage-5 Strategy Persistence (POST-RUN INVARIANT)

Agents MUST ensure that for every RUN_COMPLETE backtest:
- A corresponding folder exists at `strategies/<RUN_ID>/`
- The folder contains only:
  - `strategy.py`
  - `__pycache__/`
- The `strategies/` directory mirrors `backtests/`

If a backtest folder is deleted by the human operator, the corresponding
strategy folder MUST also be deleted.

## 6. Failure Handling

On any ambiguity or error:
- STOP
- REPORT
- WAIT for human instruction

No retries. No silent continuation.

---

End of SOP_OUTPUT Agent Summary

