---
description: Execute all active directives through the governed pipeline with Admission Gate enforcement
---

## Execute Directives Workflow

This workflow executes all directives in `backtest_directives/active/` through the full governance-first pipeline.

### Prerequisites

- Directive YAML file(s) placed in `backtest_directives/active/`
- AGENT.md (Failure Playbook) exists at project root

### Step 1: SOP Ingestion

Read and internalize all governing SOPs before any execution:

- `governance/SOP/SOP_TESTING.md`
- `governance/SOP/SOP_OUTPUT.md`
- `governance/SOP/SOP_CLEANUP.md`
- `governance/SOP/SOP_PORTFOLIO_ANALYSIS.md`
- `governance/SOP/STRATEGY_PLUGIN_CONTRACT.md`
- `AGENT.md` (Failure Playbook)

Confirm understanding of: stage ordering, artifact authority, fail-fast contract, ledger supremacy, append-only guarantees, and Admission Gate enforcement.

### Step 2: Provision-Only Run

Execute provisioning and validation ONLY (no backtesting):

// turbo

```
python tools/run_pipeline.py --all --provision-only
```

If this fails with `PROVISION_REQUIRED`:

- The strategy was auto-provisioned but has no execution logic.
- Present the strategy path to the user.
- The user must author or approve strategy logic before proceeding.
- Do NOT proceed to Step 3 until the strategy is implemented and approved.

If this succeeds (`ALLOW_EXECUTION`):

- Strategy exists and passes all semantic gates.
- Proceed to Step 3.

### Step 3: Human Review (Admission Gate)

For each directive that passed Step 2:

- Present `strategies/<STRATEGY_NAME>/strategy.py` to the user for review.
- Execution must not proceed unless user explicitly responds with APPROVED
- Do NOT skip this step. It is mandated by SOP_TESTING §4A.

If the strategy needs changes:

- Make changes as requested by the user.
- Re-run Step 2 to validate changes pass semantic validation.
- Present again for approval.

### Step 4: Full Pipeline Execution

After human approval, execute the full pipeline:

```
python tools/run_pipeline.py --all --force
```

`--force` is required only if directive state ids FAILED,
if directive is INITIALIZED or READY, run without --force.

Monitor execution through all stages:

- Stage-0: Preflight
- Stage-0.5: Semantic Validation + Admission Gate
- Stage-0.75: Dry-Run Validator
- Stage-1: Execution (per symbol)
- Stage-2: Compilation
- Stage-3: Aggregation + Snapshot + Manifest
- Stage-4: Portfolio Evaluation + Ledger Gate

### Step 5: Failure Handling

On ANY failure:

1. Classify per `AGENT.md` failure playbook.
2. Report the exact failure class from: PROVISION_REQUIRED, SCHEMA_VIOLATION, ARTIFACT_MISSING, STATE_TRANSITION_INVALID, EXECUTION_ERROR, STAGE_3_CARDINALITY_MISMATCH, STAGE_4_LEDGER_MISMATCH, SNAPSHOT_INTEGRITY_MISMATCH, MANIFEST_TAMPER_DETECTED, FILTERSTACK_ARCHITECTURAL_VIOLATION, DRYRUN_CRASH, INDICATOR_IMPORT_MISMATCH, PREFLIGHT_FAILURE, DATA_LOAD_FAILURE.
3. Do NOT attempt automatic repair.
4. Do NOT retry without addressing root cause.
5. Do NOT modify strategy code without human approval.

### Step 6: Completion Report

On successful completion, report:

- Which directives completed
- Per-symbol trade counts and PnL
- Stage-by-stage pass/fail summary
- Final directive state (PORTFOLIO_COMPLETE)

### Step 7: Deterministic Report Generation (Non-Authoritative)

After successful completion of Stage-4 (Portfolio Evaluation + Ledger Gate),
the pipeline must generate a deterministic research summary artifact.

This stage is observational only and does NOT affect directive state.

Behavior:

- Read-only access to:
  - raw/results_standard.csv
  - raw/results_risk.csv
  - raw/results_yearwise.csv

- Generate:
  backtests/<DIRECTIVE_NAME>/REPORT_SUMMARY.md

The report must contain:

- Portfolio Summary
- Per-Symbol Summary
- Volatility Edge Breakdown
- Trend Edge Breakdown

Constraints:

- Must NOT modify execution artifacts.
- Must NOT modify run_state.json.
- Must NOT modify directive state.
- Must NOT recompute indicators.
- Must NOT alter ledger data.
- Must NOT affect manifest integrity.

Failure Handling:

If report generation fails:

- Classify as REPORT_GENERATION_FAILURE.
- Log error.
- Do NOT invalidate completed directive.
- Do NOT downgrade PORTFOLIO_COMPLETE state.

This stage is non-authoritative and does not participate in governance gates.

### System Contract

The system is: Deterministic, Ledger-authoritative, Append-only, Fail-fast, Non-mutating.
Execution without compliance validation is prohibited.
