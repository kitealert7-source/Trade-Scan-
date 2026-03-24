# Trade_Scan Pipeline --- Full-Stage Execution Model

\\mermaid
flowchart TD

    Z0A[INBOX: sweep_registry_gate.py Stage -0.35] --> Z0B[namespace_gate.py Stage -0.30]
    Z0B --> Z0C[canonicalizer.py Stage -0.25]
    Z0C --> |Approve and Move| A[Start Directive from ACTIVE]
    A --> B[Load / Initialize directive_state.json]
    B --> C{Directive State?}

    C --> |PORTFOLIO_COMPLETE| Z1[Abort]
    C --> |INITIALIZED| D[Run Preflight]
    C --> |PREFLIGHT_COMPLETE| E[Resume Stage 1]
    C --> |SYMBOL_RUNS_COMPLETE| P[Go to Stage 4]
    C --> |FAILED| Z2[Abort / Require Explicit Reset via reset_directive.py]

    D --> D0A[Stage 0.5: Semantic Validation]
    D0A --> D0AA[Stage 0.55: Semantic Coverage Gate]
    D0AA --> D0B[Stage 0.75: Dry-Run Validation]
    D0B --> D1[directive_state = PREFLIGHT_COMPLETE]

    D1 --> F[Multi-Asset Batch Execution Harness]

    subgraph BATCH_EXECUTION [Multi-Asset Batch]
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

    S10 --> G[All Assets Evaluated?]

    G --> |No| F
    G --> |Yes| H[directive_state = SYMBOL_RUNS_COMPLETE]

    H --> P[Pre-Portfolio Verification]

    P --> P1[Verify Manifest Hashes]
    P1 --> |Mismatch| Z3[directive_state = FAILED]
    P1 --> |Valid| Q[Stage 4 Portfolio Eval and Candidate Promotion]

    Q --> R[directive_state = PORTFOLIO_COMPLETE]
    R --> R1[Step 7: Report Generation]
    R1 --> R2[Step 8: Capital Wrapper - Multi-Profile]
    R2 --> R3[Step 9: Post-Process Capital - Utilization Metrics]
    R3 --> R4[Step 10: Robustness Suite]
    R4 --> S[Post-Pipeline: Decoupled Artifact Formatting]
    S --> END[End]
\
## Operational Reference

### Stage Outputs

* **Stage -0.35 (sweep_registry_gate.py)**: Sweep reservation and collision enforcement.
* **Stage -0.30 (namespace_gate.py)**: Token dictionary validation for FAMILY, MODEL, FILTER, TF tokens.
* **Stage -0.25 (canonicalizer.py)**: Structural schema enforcement and canonical key relocation.
* **Stage 1 (run_stage1.py)**: Raw, immutable trade-level execution data and symbol metadata.
  * *Output*: TradeScan_State/runs/&lt;run_id&gt;/raw/results_tradelevel.csv
  * *Guard*: Zero-byte or corrupted artifact files trigger clean FAILED state transition (added 2026-03-23).
  * *Index append*: At STAGE_1_COMPLETE, `run_index.py` appends one row to `TradeScan_State/research/index.csv` (non-blocking, added 2026-03-24).
* **Stage 2 (stage2_compiler.py)**: Trade-level metrics enriched with non-standard attributes (e.g., market_regime).
  * *Output*: TradeScan_State/runs/&lt;run_id&gt;/AK_Trade_Report.xlsx
* **Stage 3 (stage3_compiler.py)**: Pure summary aggregates; explicitly isolated from trade-level state.
  * *Output*: TradeScan_State/backtests/Strategy_Master_Filter.xlsx
* **Stage 4 (filter_strategies.py)**: Candidate evaluation and promotion to the target ledger.
  * *Output*: TradeScan_State/candidates/<run_id>/ & TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx
* **Step 7 (report_generator.py)**: REPORT_SUMMARY.md from raw results CSVs. Read-only.
* **Step 8 (capital_wrapper.py)**: Multi-profile capital simulation producing deployable artifacts.
  * *Output*: summary_metrics.json, profile_comparison.json, equity_curve.png, deployable_trade_log.csv
* **Step 9 (post_process_capital.py)**: Capital utilization metric enrichment for profile_comparison.json.
* **Step 10 (robustness_suite.py)**: 14-section observational stability analysis.
* **Post-Pipeline (format_excel_artifact.py)**: Application of human-readable formatting to generated ledgers.

### Primary Artifacts

* **results_tradelevel.csv**: The root of truth for all post-execution calculations.
* **AK_Trade_Report.xlsx**: Detailed trade ledger for deep-dive analysis.
* **Strategy_Master_Filter.xlsx**: Dense overview of all executed configurations.
* **Filtered_Strategies_Passed.xlsx**: The target ledger for promoted candidate strategies.
* **STRATEGY_SNAPSHOT.manifest.json**: The cryptographic lock securing the run identity.
* **profile_comparison.json**: Multi-profile capital model results with concurrency and utilization metrics.
* **summary_metrics.json**: Deployable capital metrics per profile.

### Storage Locations

* **TradeScan_State/runs/\<run_id\>/**: Immutable per-run execution artifacts.
* **TradeScan_State/backtests/**: `{strategy_id}_{symbol}/` folders containing `raw/`, `metadata/run_metadata.json` (with full provenance fields as of 2026-03-24), `portfolio_evaluation/`.
* **TradeScan_State/research/index.csv**: Append-only flat index — 15 columns per run; 167 legacy rows + live append at each STAGE_1_COMPLETE (added 2026-03-24).
* **TradeScan_State/candidates/**: Promoted strategies that passed the candidate gate.
* **TradeScan_State/strategies/\<PF_ID\>/deployable/**: Deployable capital artifacts per strategy (atomic and composite).

### Registry

* **run_registry.json**: Authoritative lifecycle state for sandbox to candidate promotion.
* **directive_audit.log**: Append-only governance audit trail for all directive operations.
* **TradeScan_State/research/index.csv**: Append-only cross-run discoverability index (added 2026-03-24 — see Storage Locations above).

### FSM Notes (2026-03-23)

* PREFLIGHT_COMPLETE may now transition directly to STAGE_1_COMPLETE when semantic validation is cached (skip-path added to ALLOWED_TRANSITIONS).
* transition_to() now logs a [WARN] and skips gracefully if the run state directory does not exist, instead of crashing the orchestrator.

### Pipeline Notes (2026-03-24)

* At STAGE_1_COMPLETE, `stage_symbol_execution.py` calls `run_index.py:append_run_to_index()` — non-blocking append to `TradeScan_State/research/index.csv`. Failure is caught and logged; pipeline never blocked.
* `run_metadata.json` in both RUNS_DIR and BACKTESTS_DIR now carries `content_hash`, `git_commit`, `execution_model`, `schema_version="1.3.0"` for all new runs.

---
**Version**: 2.0.1 | **Last Updated**: 2026-03-24
