# System Entrypoints Registry

This document serves as the official registry of operational entrypoints for the TradeScan system. Documentation here ensures that all workflow triggers are visible, governed, and execute via standard conventions.

---

## SECTION 1 — Primary System Entrypoints

These are the authoritative entrypoints that initiate major research and operational workflows.

Entrypoint | Purpose | Triggered Pipeline Stages
--- | --- | ---
`tools/run_pipeline.py` | Master pipeline orchestrator | Stage 0 → Stage 3A
`tools/run_portfolio_analysis.py` | Governance-grade portfolio analysis | Stage 4
`tools/rebuild_all_reports.py` | Artifact & report reconstruction | Stage 2, Stage 3

---

## SECTION 2 — Execution Convention

All system tools must be executed as Python modules from the repository root. This ensures consistent import resolution and environment parity across different operating systems.

**Standard Pattern:**
```bash
python -m tools.run_pipeline <args>
python -m tools.run_portfolio_analysis <args>
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
