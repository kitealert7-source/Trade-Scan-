# 04_governance_and_guardrails

Read before changing governance gates, registry logic, naming conventions, or any guardrail.

| Document | When to read |
|---|---|
| `GUARDRAILS_WALKTHROUGH.md` | **Start here.** Covers the 6 operational guardrails + preflight check workflow. |
| `NAMING_CONVENTIONS_AUDIT.md` | Before creating identifiers, run_ids, or directory names. Defines valid schemas. |
| `RUN_REGISTRY_EXECUTION_MODEL_IMPLEMENTATION_REPORT.md` | Before touching registry logic (`PLANNED → RUNNING → COMPLETE/FAILED` transitions). |
| `RESRCH_INFRA_HARDENING_SUMMARY.md` | Context on Phase 2 hardening — dynamic engine registry, orchestrator integration. |
| `STATE_ROOT_SEPARATION_REPORT.md` | Before moving any files between Trade_Scan and TradeScan_State. Defines authority boundaries. |

**Recommended reading order:** GUARDRAILS → NAMING → RUN_REGISTRY → STATE_ROOT
