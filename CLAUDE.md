# CLAUDE.md — Agent Session Brief

## What This System Is

Three-repo research-to-execution pipeline:
- **Trade_Scan** (this repo) — research pipeline: directive → backtest → deployable strategy
- **TradeScan_State** (`../TradeScan_State`) — all pipeline output; shared artifact store
- **TS_Execution** (`../TS_Execution`) — MT5 live execution bridge; reads strategies from here

**No execution authority here. No live trading. No automation.**

---

## Before Acting — Mandatory Reads

1. `AGENT.md` — full failure playbook + 25 system invariants (**read in full before any pipeline action**)
2. `RESEARCH_MEMORY.md` — disproven approaches + accumulated findings (avoid repeating history)
3. `SYSTEM_STATE.md` — current system health snapshot

---

## Critical Invariants (top 5 — full list in AGENT.md)

1. **Fail-Fast** — any failure aborts the pipeline; never silently continue
2. **Append-Only Ledgers** — `Strategy_Master_Filter.xlsx` and `Master_Portfolio_Sheet.xlsx` are append-only
3. **Artifact Authority** — decisions derive from physical artifact existence, not memory or assumptions
4. **Snapshot Immutability** — `TradeScan_State/runs/<RUN_ID>/strategy.py` is write-once
5. **Human Gating** — no strategy enters TS_Execution without explicit human approval (PORTFOLIO_COMPLETE)

---

## Topic Index — "If you are doing X, read this first"

| Task | Document |
|---|---|
| Any pipeline run or directive work | `AGENT.md` (full) |
| Understanding pipeline stage flow | `outputs/system_reports/01_system_architecture/pipeline_flow.md` |
| Checking what entrypoints exist | `outputs/system_reports/01_system_architecture/SYSTEM_ENTRYPOINTS.md` |
| Understanding system boundaries + invariants | `outputs/system_reports/01_system_architecture/SYSTEM_SURFACE_MAP.md` |
| Touching engine code (`engine_dev/`) | `outputs/system_reports/02_engine_core/ENGINE_EXECUTION_AUDIT_v1_5_3.md` |
| Governance, naming, registry, or guardrails | `outputs/system_reports/04_governance_and_guardrails/GUARDRAILS_WALKTHROUGH.md` |
| Capital model, lot sizing, or risk | `outputs/system_reports/05_capital_and_risk_models/CAPITAL_AUDIT_REPORT.md` |
| Strategy research infrastructure or filters | `outputs/system_reports/06_strategy_research/RESEARCH_INFRASTRUCTURE_AUDIT.md` |
| Artifact provenance or storage layout | `outputs/system_reports/08_pipeline_audit/ARTIFACT_STORAGE_AUDIT_2026_03_24.md` |
| Directive state, lifecycle, or cleanup | `outputs/system_reports/10_State Lifecycle Management/Workflow_Design.md` |
| Directory/file authority questions | `outputs/system_reports/01_system_architecture/REPOSITORY_AUTHORITY_MAP.md` |

---

## Path Authority

`config/state_paths.py` — defines every output path to TradeScan_State. Never hardcode.

---

## Key Operational Commands

```bash
# Run a single directive
python tools/run_pipeline.py <DIRECTIVE_ID>

# Phase 0 validation (TS_Execution)
cd ../TS_Execution && python src/main.py --phase 0

# System preflight check
python tools/system_preflight.py
```

---

## Architecture Docs

Full document index: `outputs/system_reports/01_system_architecture/README.md`
All system reports: `outputs/system_reports/`
