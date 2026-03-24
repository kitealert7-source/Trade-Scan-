# System Entrypoints Registry

This document serves as the official registry of operational entrypoints for the TradeScan system. Documentation here ensures that all workflow triggers are visible, governed, and execute via standard conventions.

---

## SECTION 1 — Primary System Entrypoints

These are the authoritative entrypoints that initiate major research and operational workflows.

| Entrypoint | Purpose | Triggered Pipeline Stages | Key Artifacts |
| :--- | :--- | :--- | :--- |
| `tools/run_pipeline.py` | Master pipeline orchestrator | Stage -0.35 → Stage 3A | `results_tradelevel.csv`, `Strategy_Master_Filter.xlsx` |
| `tools/run_portfolio_analysis.py` | Governance-grade portfolio analysis | Stage 4 | `Master_Portfolio_Sheet.xlsx` |
| `tools/capital_wrapper.py` | Multi-profile capital model simulation | Post-Stage-4 (Step 8) | `summary_metrics.json`, `profile_comparison.json`, `equity_curve.png` |
| `tools/post_process_capital.py` | Capital utilization metric enrichment | Post-Capital (Step 9) | `profile_comparison.json` (enriched) |
| `tools/robustness_suite.py` | 14-section robustness and stability analysis | Step 10 | Per-profile analysis reports |
| `tools/filter_strategies.py` | Candidate promotion evaluation | Stage 4 | `Filtered_Strategies_Passed.xlsx` |
| `tools/format_excel_artifact.py` | Decoupled formatting execution | Post-Pipeline | Formatted `.xlsx` artifacts |
| `tools/rebuild_all_reports.py` | Artifact & report reconstruction | Stage 2, Stage 3 | Excel ledgers |

---

## SECTION 2 — Governance & Maintenance Entrypoints

These tools are used for system-level governance operations. Most require explicit human invocation and are protected under `AGENT.md` SYSTEM INVARIANTS.

| Entrypoint | Purpose | Authority Level |
| :--- | :--- | :--- |
| `tools/reset_directive.py` | Governed directive reset with reason audit log | Human-only |
| `tools/new_pass.py` | Scaffold new strategy passes without mtime/EXPERIMENT_DISCIPLINE violation | Human-assisted |
| `tools/generate_guard_manifest.py` | Regenerate SHA-256 Guard-Layer Manifest | Human-only (INVARIANT 16) |
| `tools/generate_engine_manifest.py` | Regenerate engine manifest binding | Human-only (INVARIANT 18) |
| `tools/verify_engine_integrity.py` | Verify engine hash against vault root-of-trust | Pipeline (Stage 0) |
| `tools/system_registry.py` | Run lifecycle reconciliation and stale-state cleanup | Governed |
| `tools/sweep_registry_gate.py` | Sweep reservation and collision enforcement | Pipeline (Stage -0.35) |
| `tools/namespace_gate.py` | Token dictionary enforcement | Pipeline (Stage -0.30) |
| `tools/canonicalizer.py` | Structural schema validation and canonical relocation | Pipeline (Stage -0.25) |
| `tools/run_index.py` | Append-only run index writer — called automatically at `STAGE_1_COMPLETE`; writes to `TradeScan_State/research/index.csv` | Infrastructure (auto, added 2026-03-24) |
| `tools/backfill_run_index.py` | One-time legacy backfill of `index.csv` with pre-patch runs (`schema_version="legacy"`); safe to re-run (duplicate guard) | Human-only (added 2026-03-24) |

---

## SECTION 3 — Execution Convention

All system tools must be executed as Python modules from the repository root. This ensures consistent import resolution and environment parity across different operating systems.

**Standard Pattern:**
```bash
python -m tools.run_pipeline <args>
python -m tools.run_portfolio_analysis <args>
python -m tools.capital_wrapper <args>
python -m tools.post_process_capital <args>
python -m tools.filter_strategies <args>
python -m tools.format_excel_artifact <args>
python -m tools.reset_directive <id> --reason "<justification>"
python -m tools.new_pass <source_pass> <new_pass>
```

---

## SECTION 4 — Entrypoint Governance Rule

To maintain system transparency:
1. All new operational entrypoints (tools intended for regular workflow use) **must** be documented in this registry.
2. Entrypoints must live in `tools/` and not inside `engines/`, `governance/`, or pipeline infrastructure modules.
3. Scripts located in `/tmp/` are ad-hoc scratch scripts and are **not** registered entrypoints. They must never be promoted to the `tools/` layer without an explicit implementation plan.
4. This registry acts as the "Switchboard" for the architectural surfaces defined in the `SYSTEM_SURFACE_MAP.md`.
5. Human-only entrypoints must include an explicit note on the INVARIANT that protects them.

---
**Status**: Authoritative Entrypoint Registry | **Version**: 2.0.1 | **Last Updated**: 2026-03-24
