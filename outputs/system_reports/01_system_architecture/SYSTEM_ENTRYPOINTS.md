# System Entrypoints Registry

This document serves as the official registry of operational entrypoints for the TradeScan system. Documentation here ensures that all workflow triggers are visible, governed, and execute via standard conventions.

---

## SECTION 1 — Primary System Entrypoints

These are the authoritative entrypoints that initiate major research and operational workflows.

| Entrypoint | Purpose | Triggered Pipeline Stages | Key Artifacts |
| :--- | :--- | :--- | :--- |
| `tools/run_pipeline.py` | Master pipeline orchestrator | Stage 0 → Stage 3A | `results_tradelevel.csv`, `Strategy_Master_Filter.xlsx` |
| `tools/run_portfolio_analysis.py` | Governance-grade portfolio analysis | Stage 4 | `portfolio_summary.json` |
| `tools/rebuild_all_reports.py` | Artifact & report reconstruction | Stage 2, Stage 3 | Excel ledgers |
| `tools/filter_strategies.py` | Candidate promotion evaluation | Stage 4 | `Filtered_Strategies_Passed.xlsx` |
| `tools/format_excel_artifact.py` | Decoupled formatting execution | Post-Pipeline | Formatted `.xlsx` artifacts |

---

## SECTION 2 — Execution Convention

All system tools must be executed as Python modules from the repository root. This ensures consistent import resolution and environment parity across different operating systems.

**Standard Pattern:**
```bash
python -m tools.run_pipeline <args>
python -m tools.run_portfolio_analysis <args>
python -m tools.filter_strategies <args>
python -m tools.format_excel_artifact <args>
```

---

## SECTION 3 — Entrypoint Governance Rule

To maintain system transparency:
1. All new operational entrypoints (tools intended for regular workflow use) **must** be documented in this registry.
2. Entrypoints must live in `tools/` and not inside `engines/`, `governance/`, or pipeline infrastructure modules.
3. Scripts located in `tools/tmp/` are exempt unless they are promoted to the permanent tools layer.
4. This registry acts as the "Switchboard" for the architectural surfaces defined in the `SYSTEM_SURFACE_MAP.md`.

---
**Status**: Authoritative Entrypoint Registry | **Version**: 1.0.0
