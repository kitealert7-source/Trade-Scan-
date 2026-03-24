# Infrastructure, Workflows & Capabilities Layering

## Workflows (Procedural Orchestration)

- `tools/run_pipeline.py` (top-level coordinator only)
- `tools/orchestration/pipeline_stages.py` (phase dispatcher)
- `tools/run_portfolio_analysis.py` (portfolio analysis workflow)
- `tools/filter_strategies.py` (candidate promotion workflow)
- `tools/format_excel_artifact.py` (decoupled artifact presentation styling)
- `tools/capital_wrapper.py` (multi-profile capital simulation — post-Stage-4)
- `tools/post_process_capital.py` (capital utilization metric enrichment)
- `tools/robustness_suite.py` (14-section stability analysis per profile)

## Infrastructure (Runtime Components)

- `engines/` (FilterStack, ContextView, execution core)
- `tools/pipeline_utils.py` (run/directive FSM state stores — with graceful desync guards as of 2026-03-23)
- `tools/orchestration/transition_service.py` (central transition mediation)
- `tools/orchestration/execution_adapter.py` (process execution adapter — stderr capture added 2026-03-23)
- `tools/orchestration/run_planner.py` (directive → run units)
- `tools/orchestration/run_registry.py` (authoritative on-disk run registry)
- `tools/orchestration/stage_symbol_execution.py` (Stage-1 worker — zero-byte corruption guards added 2026-03-23; run_index append call added 2026-03-24)
- `tools/run_index.py` (append-only run index writer — called at STAGE_1_COMPLETE, added 2026-03-24)
- `tools/system_logging/pipeline_failure_logger.py` (centralized failure log with 5 MB / 7-day rotation)
- `tools/canonical_schema.py`, `tools/directive_schema.py` (schema contracts)
- `tools/namespace_gate.py` (Stage -0.30 token dictionary enforcement)
- `tools/canonicalizer.py` (Stage -0.25 structural schema enforcement)
- `tools/sweep_registry_gate.py` (Stage -0.35 sweep reservation)

## Capability Map

| Pipeline Stage / Capability | Entry Script | Inputs | Primary Artifacts (Outputs) | Skill Candidate | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage -0.35** - Sweep Registry Gate | `tools/sweep_registry_gate.py` | INBOX Directive | Sweep lock in registry | Yes | Bounded reservation surface with clean collision semantics. |
| **Stage -0.30** - Namespace Gate | `tools/namespace_gate.py` | ACTIVE Directive | Pass/Fail + violation report | Yes | Token dictionary lookup with deterministic accept/reject. |
| **Stage -0.25** - Canonicalization | `tools/canonicalizer.py` | INBOX Directive | Canonical ACTIVE Directive | Yes | Schema-level structural enforcement with explicit relocation tables. |
| **Stage 0** - Strategy Gen | `tools/strategy_provisioner.py` | ACTIVE Directive | `strategies/<strategy>/strategy.py` | Yes | Deterministic transform with clean I/O boundary. |
| **Stage 0** - Admission Gates | `tools/directive_linter.py`, `tools/sweep_registry_gate.py` | INBOX Directive | Canonical ACTIVE Directive, Registry Lock | Yes | Strict INBOX-to-ACTIVE canonical routing and locking. |
| **Stage 0** - Preflight Gates | `tools/exec_preflight.py`, `tools/orchestration/stage_preflight.py` | ACTIVE Directive, strategy | Pass/Fail state | Yes | Bounded validation surface and clear outcomes. Full stderr capture on failure. |
| **Stage 0** - Run Planning | `tools/orchestration/run_planner.py` | ACTIVE Directive, symbols | Planned run set | Yes | Pure planning logic, no heavy execution side effects. |
| **Stage 0** - Registry | `tools/orchestration/run_registry.py` | `run_registry.json` | Updated `run_registry.json` | No | Core orchestration infra, shared mutable authority. |
| **Stage 1** - Execution Worker | `tools/orchestration/stage_symbol_execution.py` | Planned run, data | `TradeScan_State/runs/<run_id>/raw/results_tradelevel.csv`, `results_risk.csv` | Partial | Worker logic is skillable; state authority remains infra. Zero-byte corruption guards active. |
| **Stage 1** - Run Index Append | `tools/run_index.py` | `run_metadata.json` + `results_standard.csv` + `results_risk.csv` | `TradeScan_State/research/index.csv` (one appended row) | No | Append-only infrastructure; FileLock-protected; non-blocking (added 2026-03-24). |
| **Governance** - Legacy Index Backfill | `tools/backfill_run_index.py` | `BACKTESTS_DIR` scan | `index.csv` legacy rows (`schema_version="legacy"`) | No | Human-only one-time script; duplicate guard makes re-runs safe (added 2026-03-24). |
| **Stage 2** - Trade Reporting | `tools/stage2_compiler.py` | Stage-1 records | `TradeScan_State/runs/<run_id>/AK_Trade_Report.xlsx` | No | Tight coupling with pipeline gates and artifact contracts. |
| **Stage 3** - Aggregation | `tools/stage3_compiler.py` | Stage-2 records | `TradeScan_State/backtests/Strategy_Master_Filter.xlsx` | No | Schema enforcement and explicitly isolated summary logic derived solely from Stage 2. |
| **Stage 4** - Candidate Promotion | `tools/filter_strategies.py` | Master Filter, Registry | `TradeScan_State/candidates/<run_id>/` & `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx` | No | System state mutation, ledger authority, sandbox migration. |
| **Stage 5** - Portfolio Post-Stage | `tools/orchestration/stage_portfolio.py` | Stage-3 Ledgers | `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx` | No | Multi-system side effects and portfolio ledger authority. |
| **Step 7** - Report Generation | `tools/report_generator.py` | Raw results CSVs | `REPORT_SUMMARY.md` | Yes | Read-only deterministic transform from raw artifacts. |
| **Step 8** - Capital Wrapper | `tools/capital_wrapper.py` | Portfolio trade log | `summary_metrics.json`, `profile_comparison.json`, `equity_curve.png` | Partial | Multi-profile simulation; profile logic is reusable but artifact emission is pipeline-bound. |
| **Step 9** - Capital Post-Process | `tools/post_process_capital.py` | `profile_comparison.json` | Enriched `profile_comparison.json` with utilization metrics | Yes | Pure enrichment transform, no state mutation. |
| **Step 10** - Robustness Suite | `tools/robustness_suite.py` | Stage-1 artifacts | 14-section analysis reports | Yes | Observational only; no pipeline state mutation. |
| **Post-Pipeline** - Formatting | `tools/format_excel_artifact.py` | Target Ledgers | Formatted `.xlsx` artifacts | Yes | Presentation-focused deterministic transformation. |

---

## Top Skill Candidates (Current)

1. Strategy Generation
2. Preflight + Semantic Validation
3. Namespace Gate + Canonicalization
4. Run Planning
5. Report Generation
6. Capital Post-Processing
7. Robustness / Validation suites
8. Reporting/Formatting

## Refactor Guardrails (Adopted)

- File review trigger: `> 300 LOC`
- File hard ceiling: `> 500 LOC` (must refactor)
- Function target: `40-60 LOC`
- Function review trigger: `> 80 LOC`
- Function hard limit: `> 120 LOC`

---
**Version**: 2.0.1 | **Last Updated**: 2026-03-24
