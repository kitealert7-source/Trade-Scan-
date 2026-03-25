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

## SECTION 2A — Monitoring & Self-Healing Entrypoints

These tools operate externally to the research pipeline and govern the liveness of TS_Execution.

| Entrypoint | Purpose | Authority Level |
| :--- | :--- | :--- |
| `tools/orchestration/watchdog_daemon.py` | Continuous heartbeat monitor for `ts_execution/src/main.py`. Polls every 60s. SOFT breach (180s) → warning log. HARD breach (300s) → kill + auto-restart. DEGRADED → heartbeat alive but no bar processed in 2h. Storm guard: max 3 restarts per 10-min window. Single-instance enforced via `watchdog.pid`. | Human-started (must start before execution, once per session) |
| `tools/orchestration/test_watchdog.py` | Simulation harness for watchdog scenarios (Normal / Kill / Degraded) without requiring MT5. Injects synthetic state files for integration testing. | Human-only (testing) |

**Runtime artifacts** (written to `ts_execution/outputs/logs/`, external to Trade_Scan):

| File | Writer | Purpose |
| :--- | :--- | :--- |
| `heartbeat.log` | `ts_execution/src/main.py` heartbeat thread | Liveness signal, written every 60s, rotates at 5 MB |
| `execution.pid` | `ts_execution/src/main.py` startup | Process ID for watchdog; deleted on clean exit |
| `execution_state.json` | `ts_execution/src/main.py` per-bar callback | `last_bar_time` for logical stall detection; deleted on clean exit |
| `watchdog_daemon.log` | `watchdog_daemon.py` | All watchdog decisions and recovery actions, rotates at 5 MB |
| `watchdog_guard.json` | `watchdog_daemon.py` | Restart storm counter |
| `watchdog.pid` | `watchdog_daemon.py` | Single-instance guard; deleted on clean exit |

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
**Status**: Authoritative Entrypoint Registry | **Version**: 2.0.2 | **Last Updated**: 2026-03-25
