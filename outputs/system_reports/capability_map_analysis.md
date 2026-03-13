# Infrastructure, Workflows & Capabilities Layering (Updated)

## Workflows (Procedural Orchestration)
- `tools/run_pipeline.py` (top-level coordinator only)
- `tools/orchestration/pipeline_stages.py` (phase dispatcher)
- `tools/run_portfolio_analysis.py` (portfolio analysis workflow)
- `tools/rebuild_all_reports.py` (batch reporting workflow)

## Infrastructure (Runtime Components)
- `engines/` (FilterStack, ContextView, execution core)
- `tools/pipeline_utils.py` (run/directive FSM state stores)
- `tools/orchestration/transition_service.py` (central transition mediation)
- `tools/orchestration/execution_adapter.py` (process execution adapter)
- `tools/orchestration/run_planner.py` (directive -> run units)
- `tools/orchestration/run_registry.py` (authoritative on-disk run registry)
- `tools/canonical_schema.py`, `tools/directive_schema.py` (schema contracts)

## Capability Map
| Capability | Entry Script | Inputs | Outputs | Skill Candidate | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Strategy Generation | `tools/strategy_provisioner.py` | Directive | `strategy.py` | Yes | Deterministic transform with clean I/O boundary. |
| Preflight + Semantic Gates | `tools/exec_preflight.py`, `tools/orchestration/stage_preflight.py` | Directive, strategy | Pass/Fail + state transitions | Yes | Bounded validation surface and clear outcomes. |
| Run Planning | `tools/orchestration/run_planner.py` | Directive, symbols | Planned run set + registry entries | Yes | Pure planning logic, no heavy execution side effects. |
| Run Registry Coordination | `tools/orchestration/run_registry.py` | Registry file | Claimed/updated run states | No | Core orchestration infrastructure, shared mutable authority. |
| Atomic Backtest Worker | `tools/orchestration/stage_symbol_execution.py` + `tools/skill_loader.py` | Planned run, data | Per-run artifacts + run completion state | Partial | Worker logic is skillable; registry/state authority should remain infra. |
| Stage 2/3 Aggregation | `tools/stage2_compiler.py`, `tools/stage3_compiler.py` | Per-run artifacts | Master filter outputs | No | Tight coupling with pipeline/state gates and artifact contracts. |
| Portfolio + Deployable Post-Stage | `tools/orchestration/stage_portfolio.py` | Aggregated artifacts | Portfolio ledger + deployable checks | No | Multi-system side effects and ledger authority. |
| Reporting/Formatting | `tools/report_generator.py`, `tools/format_excel_artifact.py` | Raw artifacts | `.md` / formatted `.xlsx` | Yes | Presentation-focused deterministic transformation. |

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
