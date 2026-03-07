# Infrastructure, Workflows & Capabilities Layering

**WORKFLOWS (Procedural Orchestration):**

* `run_pipeline.py` (Master Execution Pipeline)
* `run_portfolio_analysis.py` (Portfolio Pipeline Orchestrator)
* `rebuild_all_reports.py` (Batch reporting workflow)

**INFRASTRUCTURE (Engine/Runtime Components):**

* `engines/` (FilterStack, ContextView, core trading logic)
* `pipeline_utils.py` (State management, run_id generation)
* `canonical_schema.py`, `directive_schema.py` (Base definitions)

**CAPABILITIES (Bounded Operational Units):**
*Mapped below.*

### Capability Map

| Capability | Entry Script | Dependencies | Inputs | Outputs | Skill Candidate (Yes/No) | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Strategy Generation** | `strategy_provisioner.py` | `directive_schema.py` | Directive (`.txt`) | `strategy.py` | **Yes** | Highly deterministic translation layer; outputs isolated Python code from config text. |
| **Preflight Validation** | `exec_preflight.py` | `semantic_validator.py`, `strategy_dryrun_validator.py` | Directive (`.txt`), `strategy.py` | State transition (Pass/Fail) | **Yes** | Bounded static-analysis and dry-run guard sequence. Distinct logic from generation. |
| **Atomic Backtest Execution** | `run_stage1.py` | `execution_emitter_stage1.py`, `engines/` | `strategy.py`, Price Data | `results_tradelevel.csv`, run metadata | **Yes** | Heavy computational workload with strictly defined inputs (script + data) and defined outputs. |
| **Data Aggregation (Stage 2/3)** | `stage2_compiler.py`, `stage3_compiler.py` | `pipeline_utils.py` | Atomic backtest directories | `Strategy_Master_Filter.xlsx` rows | **No** | Heavy pipeline/state entanglement. Too coupled to the orchestrator's state management. |
| **Robustness Testing** | `verify_batch_robustness.py` | `validate_lookahead.py`, `validate_high_vol.py` | Trade results, Price Data | Validation Pass/Fail | **Yes** | Self-contained statistical/stress testing. Standardized checks applied post-execution. |
| **Portfolio Evaluation** | `portfolio_evaluator.py` | `profile_selector.py`, `capital_wrapper.py` | Backtest CSVs across assets | `profile_comparison.json`, charts, `Master_Portfolio_Sheet` rows | **Yes** | Highly complex math/capital modeling. Benefits from tight functional boundaries. |
| **Excel & Report Formatting** | `format_excel_artifact.py`, `report_generator.py` | None | Raw Excel/CSV data | Formatted `.xlsx` / `.md` files | **Yes** | Pure presentation logic. Deterministic application of styling rules to raw data grids. |
| **Cleanup & Reconciliation** | `cleanup_reconciler.py` | Ledgers (`.xlsx`) | Filesystem state, Auth Ledgers | Purged stale directories | **No** | Requires sweeping filesystem/state access; acts more like an infra-workflow than a bounded data transformation. |

---

### Top 5 Candidates for Skills Conversion

Based on clear I/O boundaries, deterministic behavior, and functional isolation, the following capabilities are the strongest candidates for migration to Skills:

1. **`Strategy Provisioning`** (Translating Directives to `strategy.py`)
2. **`Excel Artifact Formatting`** (Applying strict visual/rounding compliance)
3. **`Preflight Validation`** (Semantic/Dry-run capability checks)
4. **`Robustness Testing`** (Lookahead/Vol/Trend statistical validation)
5. **`Atomic Backtest Execution`** (Stateless single-asset engine execution)
