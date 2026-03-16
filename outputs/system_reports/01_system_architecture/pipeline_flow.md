# Trade_Scan Pipeline v1.0 --- Two-Layer Execution Model

``` mermaid
flowchart TD

    A[Start Directive] --> B[Load / Initialize directive_state.json]
    B --> C{Directive State?}

    C -->|PORTFOLIO_COMPLETE| Z1[Abort]
    C -->|INITIALIZED| D[Run Preflight]
    C -->|PREFLIGHT_COMPLETE| E[Resume Stage 1]
    C -->|SYMBOL_RUNS_COMPLETE| P[Go to Stage 4]
    C -->|FAILED| Z2[Abort / Require Explicit Reset]

    D --> D1[directive_state = PREFLIGHT_COMPLETE]

    D1 --> F[Per-Symbol Execution Loop]

    subgraph SYMBOL_EXECUTION [Per-Symbol FSM]
        F --> S1[STAGE_1_START]
        S1 --> S2[STAGE_1_COMPLETE]
        S2 --> S3[STAGE_2_START]
        S3 --> S4[STAGE_2_COMPLETE]
        S4 --> S5[STAGE_3_START]
        S5 --> S6[STAGE_3_COMPLETE]
        S6 --> S7[STAGE_3A_START]
        S7 --> S8[Verify Snapshot + Hash Artifacts]
        S8 --> S9[STAGE_3A_COMPLETE]
        S9 --> S10[COMPLETE]
    end

    S10 --> G[All Symbols Complete?]

    G -->|No| F
    G -->|Yes| H[directive_state = SYMBOL_RUNS_COMPLETE]

    H --> P[Pre-Portfolio Verification]

    P --> P1[Verify Manifest Hashes]
    P1 -->|Mismatch| Z3[directive_state = FAILED]
    P1 -->|Valid| Q[Stage 4 Portfolio Eval & Candidate Promotion]

    Q --> R[directive_state = PORTFOLIO_COMPLETE]
    R --> S[Post-Pipeline: Decoupled Artifact Formatting]
    S --> END[End]
```

## Operational Reference

### Stage Outputs

* **Stage 1 (`run_stage1.py`)**: Raw, immutable trade-level execution data and symbol metadata.
  * *Output*: `TradeScan_State/runs/<run_id>/raw/results_tradelevel.csv`
* **Stage 2 (`stage2_compiler.py`)**: Trade-level metrics enriched with non-standard attributes (e.g., `market_regime`).
  * *Output*: `TradeScan_State/runs/<run_id>/AK_Trade_Report.xlsx`
* **Stage 3 (`stage3_compiler.py`)**: Pure summary aggregates; explicitly isolated from trade-level state.
  * *Output*: `TradeScan_State/backtests/Strategy_Master_Filter.xlsx`
* **Stage 4 (`filter_strategies.py`)**: Candidate evaluation and promotion to the target ledger.
  * *Output*: `TradeScan_State/candidates/<run_id>/` & `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx`
* **Post-Pipeline (`format_excel_artifact.py`)**: Application of human-readable formatting to generated ledgers.

### Primary Artifacts

* **`results_tradelevel.csv`**: The root of truth for all post-execution calculations.
* **`AK_Trade_Report.xlsx`**: Detailed trade ledger for deep-dive analysis.
* **`Strategy_Master_Filter.xlsx`**: Dense overview of all executed configurations.
* **`Filtered_Strategies_Passed.xlsx`**: The target ledger for promoted candidate strategies.
* **`manifest.json`**: The cryptographic lock securing the run identity against silent modifications.

### Storage Locations

* **`TradeScan_State/runs/<run_id>/`**: Immutable per-run execution artifacts.
* **`TradeScan_State/backtests/`**: Central reporting artifacts (Master Filter, trade reports).
* **`TradeScan_State/candidates/`**: Promoted strategies that passed the candidate gate.

### Registry

* **`run_registry.json`**: Authoritative lifecycle state for sandbox → candidate promotion.
