# TradeScan System Surface Architecture Map

## Architecture Scope
This document defines the structural architecture of the Trade_Scan platform. It provides a mapping of repository layers, governance gates, and execution components. It does not describe specific strategy logic, indicator implementations, or research methodology.

---

This document serves as the authoritative top-level architectural map for the Trade_Scan research platform. It defines the system layers, repository structure, and the operational boundaries between source code and runtime state.

---

## SECTION 1 — System Layer Overview

The platform is organized into seven distinct architectural layers, each with a strict responsibility boundary.

| Layer | Purpose | Primary Folders | Key Components |
| :--- | :--- | :--- | :--- |
| **Directive** | Research intent definition | `backtest_directives/` | YAML Directives |
| **Governance** | Safety & integrity gating | `governance/` | `preflight.py`, `semantic_validator.py`, `namespace_gate.py`, `canonicalizer.py` |
| **Pipeline** | Stage orchestration and execution coordination | `tools/orchestration/` | Infrastructure: `tools/orchestration/`, Entrypoint: `tools/run_pipeline.py` |
| **Engine** | Trade execution & simulation | `engines/`, `engine_dev/` | `filter_stack.py`, `execution_loop.py` |
| **Strategy** | Trading logic implementation | `strategies/` | Generated `strategy.py` files |
| **Tools** | Operational control panel | `tools/` | `run_portfolio_analysis.py`, `capital_wrapper.py`, `post_process_capital.py`, Maintenance tools |
| **State** | Runtime artifacts & history | `TradeScan_State/` | `runs/`, `backtests/`, `registry/`, `strategies/` (deployable artifacts) |

---

## SECTION 2 — Repository Directory → Layer Mapping

The system follows a predictable mapping between the physical directory structure and the architectural layers.

| Directory | Layer | Responsibility |
| :--- | :--- | :--- |
| `tools/` | Tools | Top-level operational entry points and CLI utilities. |
| `tools/orchestration/` | Pipeline | Logic for coordinating multi-stage pipeline transitions. |
| `tools/system_logging/` | Pipeline | Centralized failure logging with automatic rotation (5 MB / 7-day policy). |
| `governance/` | Governance | Safety gates, admission controllers, and compliance checkers. |
| `engines/` | Engine | Core research engines and signal processing stacks. |
| `strategies/` | Strategy | Target directory for generated and tested trading strategies. |
| `indicators/` | Engine | Library of technical indicators used by the execution engine. |
| `outputs/` | Tools/State | Generated reports, audits, and system documentation. |
| `config/` | Pipeline/Engine | Global configuration for pathing, data roots, and thresholds. |
| `TradeScan_State/` | State | **External Root** for all non-source runtime artifacts. |
| `TradeScan_State/strategies/` | State | Deployable capital artifacts per strategy (atomic and composite portfolios). |

---

## SECTION 3 — Operational Entry Points

Operational entry points are the primary interfaces for system interaction.

| Entrypoint | Purpose | Primary Stages | Primary Artifacts |
| :--- | :--- | :--- | :--- |
| `run_pipeline.py` | Full directive execution | Stage 0 → Stage 3A | `results_tradelevel.csv`, `Strategy_Master_Filter.xlsx` |
| `run_portfolio_analysis.py` | Governance-grade portfolio simulation | Stage 4 | `portfolio_summary.json` |
| `capital_wrapper.py` | Capital model simulation across profiles | Post-Stage-4 | `summary_metrics.json`, `profile_comparison.json` |
| `post_process_capital.py` | Capital utilization metrics enrichment | Post-Capital | `profile_comparison.json` (enriched) |
| `format_excel_artifact.py` | Decoupled Excel styling applied to generated ledgers | Post-Pipeline Workflow | Formatted `.xlsx` artifacts |

---

## SECTION 4 — Governance Enforcement Points

Safety gates are placed at critical transition boundaries to ensure system integrity.

Gate | Layer | Protection Provided
--- | --- | ---
`directive_linter.py` | Stage -0.35 | Admission Gate: Manages INBOX to ACTIVE canonical routing, preventing unregistered sweep collisions.
`namespace_gate.py` | Stage -0.30 | Token dictionary enforcement for FAMILY, MODEL, FILTER, and timeframe tokens.
`canonicalizer.py` | Stage -0.25 | Strict structural schema enforcement; unknown keys, misplaced blocks, and type mismatches cause HARD FAIL.
`preflight.py` | Stage 0 | Data health gate; ensures temporal baseline integrity, data availability gate, and system readiness.
`semantic_validator.py` | Stage 0.5 | AST-level guard; prevents illegal regime or engine logic access.
`strategy_dryrun_validator.py` | Stage 0.75 | Dry-Run Strategy Import Validation before execution.
`semantic_coverage_checker.py` | Stage 0.55 | Logic gate; ensures all directive parameters are used in strategy.
`verify_engine_integrity.py` | Stage 0 | Hash gate; detects unauthorized mutations in core engine code.
`FilterStack` | Engine | Bar-by-bar runtime gate; enforces strict signal/execution rules.

---

## SECTION 5 — Execution Engine Components

The engine layer (currently **Universal Research Engine v1.5.3**) ensures that bar-by-bar simulation is 100% deterministic and reproducible.

- **`engines/filter_stack.py`**: The authoritative gatekeeper for trade entry and exit signals. It enforces regime-aware execution logic.
- **`execution_loop.py`**: (Located in `engine_dev/`) The core iterator that processes historical bars and emits trade events.
- **`capital_wrapper`**: A deterministic event-based simulator that applies capital and risk constraints post-execution. Emits structured deployable artifacts per capital profile.
- **`portfolio_evaluator`**: Cross-instrument engine that reconciles individual symbol results into a unified portfolio view.
- **`post_process_capital.py`**: Enriches `profile_comparison.json` with utilization-based capital insights per profile.

### Capital Profiles (Current)

| Profile | Description |
| :--- | :--- |
| `RAW_MIN_LOT_V1` | Baseline: fixed 0.01 lot, no portfolio constraints. Pure directional edge measure. |
| `CONSERVATIVE_V1` | Risk-managed profile with strict heat and leverage caps. |
| `AGGRESSIVE_V1` | Higher-utilization profile for maximum return capture. |
| `BOUNDED_MIN_LOT_V1` | Min-lot with bounded drawdown constraints. |
| `MIN_LOT_FALLBACK_UNCAPPED_V1` | Min-lot with no concurrency ceiling. |

### Concurrency Metrics (per capital profile)

Each profile in `profile_comparison.json` now carries three concurrency fields:
- `total_constituent_runs`: count of atomic run IDs forming the portfolio.
- `actual_max_concurrent_trades`: observed peak concurrent trades during the backtest period.
- `configured_concurrency_cap`: explicit concurrency limit if set; `null` otherwise.

---

## SECTION 6 — Pipeline Execution Flow

The system operates as a sequence of governing and executing stages.

1. **Stage -0.35 — Sweep Registry Gate**: Sweep reservation and collision rejection.
2. **Stage -0.30 — Namespace Gate**: Token dictionary enforcement (`namespace_gate.py`).
3. **Stage -0.25 — Canonicalization**: Structural schema validation (`canonicalizer.py`).
4. **Stage 0 — Preflight**: Data availability, temporal coverage, and system health checks (`preflight.py`).
5. **Stage 0.5 — Semantic Validation**: Code-level inspection of strategies (`semantic_validator.py`).
6. **Stage 0.55 — Semantic Coverage**: Parameter coverage gate (`semantic_coverage_checker.py`).
7. **Stage 0.75 — Dry Run**: Execution smoke test in a sandbox environment.
8. **Stage 1 — Execution**: Multi-symbol bar-by-bar simulation (`run_stage1.py`). Corrupted/zero-byte output artifacts now trigger clean `FAILED` transitions.
9. **Stage 2 — Reporting**: Derivation of trade-level metrics and Excel reports.
10. **Stage 3 — Aggregation**: Construction of master strategy filters.
11. **Stage 3A — Manifest Binding**: Generation of SHA-256 manifests to lock the run identity.
12. **Stage 4 — Portfolio Evaluation**: Portfolio-level simulation, candidate promotion, and ledger consolidation.
13. **Workflow — Capital Wrapper**: Deployable capital artifact generation across multiple profiles.
14. **Workflow — Post-Process Capital**: Enrichment of profile metrics with utilization-based capital insights.
15. **Workflow — Artifact Formatting**: Decoupled presentation styling of output ledgers/reports.
16. **Workflow — Robustness Suite**: 14-section stability analysis (Monte Carlo, Bootstrap, Friction Stress).

*References*: [pipeline_flow.md](pipeline_flow.md)

---

## SECTION 7 — System State Boundary

A fundamental architectural rule is the **separation of Source and State**.

- **Trade_Scan (Source)**: Contains 100% immutable source code and documentation.
- **TradeScan_State (State)**: Contains 100% mutable (or append-only) runtime artifacts.

**Typical State Artifacts (Stored Externally):**
- `runs/`: Snapshot strategies and raw execution data.
- `candidates/`: Strategies undergoing research validation.
- `registry/`: The authoritative run and sweep lifecycle ledger.
- `backtests/`: Central reporting artifacts like Master Filter.
- `strategies/`: Deployable capital artifacts (`summary_metrics.json`, `profile_comparison.json`, equity curves).
- `logs/`: Time-series execution logs. Rotated automatically at 5 MB or 7 days (whichever comes first), retaining 4 archives.

**Rationale**: Keeping state external ensures the repository remains lean, portable, and git-clean, while providing a clear audit trail of research history.

---

## SECTION 7A — Data Authority Hierarchy

While the system strictly separates Source and State, the State layer itself is internally structured into a strict authority hierarchy:

```mermaid
flowchart TD
    subgraph AL [Authority Layer]
        A1[results_tradelevel.csv]
        A2[manifest.json]
    end

    subgraph CL [Computation Layer]
        C1[Trade reports]
        C2[Master filter]
    end

    subgraph RL [Research Layer]
        R1[regime analytics]
        R2[multi-run studies]
    end

    subgraph DL [Deployable Layer]
        D1[summary_metrics.json]
        D2[profile_comparison.json]
    end

    AL --> CL
    CL --> RL
    CL --> DL
```

1. **Authority Layer (Immutable System Truth)**: Cryptographically locked run histories and primitive execution footprints.
   - `results_tradelevel.csv`, `results_risk.csv`, `manifest.json`, `run_registry.json`

2. **Computation / Reporting Layer (Deterministic Derived Artifacts)**: Human-readable aggregations and ledgers.
   - `AK_Trade_Report.xlsx`, `Strategy_Master_Filter.xlsx`, `Filtered_Strategies_Passed.xlsx`, `portfolio_summary.json`

3. **Deployable Layer (Capital Model Outputs)**: Per-strategy deployable capital artifacts across all profiles.
   - `summary_metrics.json`, `profile_comparison.json`, `deployable_trade_log.csv`, `equity_curve.png`

4. **Research / Analysis Layer (Exploratory)**: Regime analytics, multi-run correlation datasets, and robustness reports.

---

## SECTION 8 — Operational Surface Map

The system exposes specialized surfaces for different operational needs.

Surface | Interaction Point | Primary Actors
--- | --- | ---
**Human Control Surface** | `tools/` | Researchers & DevOps
**Governance Surface** | `governance/` | Auditors & Admission Gates
**Execution Surface** | `engines/` | Execution Engines
**Pipeline Surface** | `tools/orchestration/` | System Orchestrators
**Strategy Surface** | `strategies/` | Strategy Generators
**Capital Surface** | `tools/capital_wrapper.py`, `tools/post_process_capital.py` | Capital Modelers

These layers interact via **Directives** (Inputs) and **Registries/Manifests** (State Handshakes), ensuring no layer bypasses the governance gates.

---

## SECTION 8A — Control Flow Boundaries

The platform enforces strict control flow boundaries between architectural layers to ensure governance cannot be bypassed.

- **Directive → Pipeline**: Research intent is ingested by the orchestrator.
- **Pipeline → Governance**: The orchestrator submits artifacts to validation gates.
- **Pipeline → Engine**: Upon gate clearance, the orchestrator dispatches execution.
- **Engine → State**: Execution results and snapshots are emitted to the external state root.
- **State → Tools**: Analysis and reporting tools ingest state artifacts for evaluation.

**Governance Bound**: No execution (Engine) or reporting (Tools) may proceed without explicit validation (Governance) handshakes.

---

## SECTION 9 — Architecture Diagram

The flow of research intent to finalized state:

```mermaid
flowchart LR
    D[Directive] --> G{Governance}
    G --> |Pass| P[Pipeline]
    P --> E[Engines]
    E --> S[Strategies]
    S --> ST[(State)]
    ST --> CW[Capital Wrapper]
    CW --> DEP[(Deployable Artifacts)]
    
    subgraph Boundary [Code Repository]
    D
    G
    P
    E
    S
    end
    
    ST -.-> |Registry Audit| G
```

---

## SECTION 10 — Architectural Principles

The system is governed by **25 codified invariants** (see `AGENT.md` SYSTEM INVARIANTS). The core tenets are:

1. **Deterministic Execution**: The same data + same code MUST produce the same results.
2. **Immutable Run Artifacts**: Once a run is bound, its strategy code and manifests are frozen.
3. **Registry-Based Lifecycle Tracking**: All run states are tracked in authoritative central ledgers.
4. **Governance-First Pipeline Admission**: No execution occurs without preflight and semantic approval.
5. **Separation of Source and Runtime State**: Ensures repository integrity and scalable data management.
6. **Decoupled Presentation Constraints**: Computation must emit clean structuring data; dedicated styling orchestrators apply human-readable formats independently.
7. **Scratch Script Placement**: All ad-hoc agent scripts go to `/tmp/` only. The repository root is reserved for governed toolset artifacts.

---
**Status**: Top-Level Authority Map | **Version**: 2.0.0 | **Last Updated**: 2026-03-23
