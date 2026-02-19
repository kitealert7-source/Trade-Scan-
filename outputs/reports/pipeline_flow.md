# Trade_Scan Pipeline v1.0 --- Two-Layer Execution Model

``` mermaid
flowchart TD

    A[Start Directive] --> B[Load / Initialize directive_state.json]
    B --> C{Directive State?}

    C -->|PORTFOLIO_COMPLETE| Z1[Abort]
    C -->|INITIALIZED| D[Run Preflight]
    C -->|PREFLIGHT_COMPLETE| E[Resume Stage 1]
    C -->|SYMBOL_RUNS_COMPLETE| P[Go to Stage 4]
    C -->|FAILED| Z2[Abort Unless --force]

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
    P1 -->|Valid| Q[Stage 4 Portfolio Evaluation]

    Q --> R[directive_state = PORTFOLIO_COMPLETE]
    R --> END[End]
```
