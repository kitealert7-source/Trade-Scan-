# 05_capital_and_risk_models

Read before touching capital formulas, lot sizing, pip values, or risk model logic.

| Document | When to read |
|---|---|
| `CAPITAL_AUDIT_REPORT.md` | **Start here.** Full formula transparency for all capital metrics (`effective_capital`, drawdown, etc). |
| `CAPITAL_ALLOCATION_REPORT.md` | Portfolio-level allocation logic and constraints. |
| `CAPITAL_SIZING_AUDIT.md` | Lot sizing formulas and validation rules. |
| `CAPITAL_WRAPPER_SAFETY_AUDIT.md` | Safety invariants in `tools/capital_wrapper.py` — equity floor, leverage cap. |
| `DYNAMIC_PIP_VALUE_FEASIBILITY.md` | Research on dynamic pip value — read before changing pip computation. |

**Capital model invariant:** $1,000 per-symbol, $10,000 total portfolio, 5× leverage cap (AGENT.md §20).
