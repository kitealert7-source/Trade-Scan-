# Infrastructure, Workflows & Capabilities Layering (Updated)

## Workflows (Procedural Orchestration)

- `tools/run_pipeline.py` (top-level coordinator only)
- `tools/orchestration/pipeline_stages.py` (phase dispatcher)
- `tools/run_portfolio_analysis.py` (portfolio analysis workflow)
- `tools/filter_strategies.py` (candidate promotion workflow)
- `tools/format_excel_artifact.py` (decoupled artifact presentation styling)

## Infrastructure (Runtime Components)

- `engines/` (FilterStack, ContextView, execution core)
- `tools/pipeline_utils.py` (run/directive FSM state stores)
- `tools/orchestration/transition_service.py` (central transition mediation)
- `tools/orchestration/execution_adapter.py` (process execution adapter)
- `tools/orchestration/run_planner.py` (directive -> run units)
- `tools/orchestration/run_registry.py` (authoritative on-disk run registry)
- `tools/canonical_schema.py`, `tools/directive_schema.py` (schema contracts)

## Capability Map

| Pipeline Stage / Capability | Entry Script | Inputs | Primary Artifacts (Outputs) | Skill Candidate | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 0** - Strategy Gen | `tools/strategy_provisioner.py` | Directive | `strategies/<strategy>/strategy.py` | Yes | Deterministic transform with clean I/O boundary. |
| **Stage 0** - Preflight Gates | `tools/exec_preflight.py`, `tools/orchestration/stage_preflight.py` | Directive, strategy | Pass/Fail state, Canonical forms | Yes | Bounded validation surface and clear outcomes. |
| **Stage 0** - Run Planning | `tools/orchestration/run_planner.py` | Directive, symbols | Planned run set | Yes | Pure planning logic, no heavy execution side effects. |
| **Stage 0** - Registry | `tools/orchestration/run_registry.py` | `run_registry.json` | Updated `run_registry.json` | No | Core orchestration infra, shared mutable authority. |
| **Stage 1** - Execution Worker | `tools/orchestration/stage_symbol_execution.py` | Planned run, data | `TradeScan_State/runs/<run_id>/raw/results_tradelevel.csv`, `results_risk.csv` | Partial | Worker logic is skillable; state authority remains infra. |
| **Stage 2** - Trade Reporting | `tools/stage2_compiler.py` | Stage-1 records | `TradeScan_State/runs/<run_id>/AK_Trade_Report.xlsx` | No | Tight coupling with pipeline gates and artifact contracts. |
| **Stage 3** - Aggregation | `tools/stage3_compiler.py` | Stage-1 records | `TradeScan_State/backtests/Strategy_Master_Filter.xlsx` | No | Schema enforcement and explicitly isolated summary logic. |
| **Stage 4** - Candidate Promotion | `tools/filter_strategies.py` | Master Filter, Registry | `TradeScan_State/candidates/<run_id>/` & `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx` | No | System state mutation, ledger authority, sandbox migration. |
| **Stage 5** - Portfolio Post-Stage | `tools/orchestration/stage_portfolio.py` | Stage-3 Ledgers | `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx` | No | Multi-system side effects and portfolio ledger authority. |
| **Post-Pipeline** - Formatting | `tools/format_excel_artifact.py` | Target Ledgers | Formatted `.xlsx` artifacts | Yes | Presentation-focused deterministic transformation. |

---

## Top Skill Candidates (Current)

1. Strategy Generation
2. Preflight + Semantic Validation
3. Run Planning
4. Reporting/Formatting
5. Robustness/Validation suites

## Refactor Guardrails (Adopted)

- File review trigger: `> 300 LOC`
- File hard ceiling: `> 500 LOC` (must refactor)
- Function target: `40-60 LOC`
- Function review trigger: `> 80 LOC`
- Function hard limit: `> 120 LOC`
