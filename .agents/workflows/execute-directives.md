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

### Step 8: Capital Wrapper Execution (Deployable Artifact Emission)

After the deterministic report in Step 7, run the capital wrapper to simulate
multi-profile portfolio equity paths and emit all deployable artifacts.

This step derives from the authoritative `backtests/<RUN_ID>/raw/results_tradelevel.csv`
files written by Stage-1. It is read-only with respect to all prior pipeline artifacts.

// turbo

```
python tools/capital_wrapper.py <DIRECTIVE_NAME>
```

Where `<DIRECTIVE_NAME>` is the base strategy prefix (e.g. `AK34_FX_PORTABILITY_4H`).

Profiles executed in a single pass:

- `CONSERVATIVE_V1`
- `AGGRESSIVE_V1`

Outputs emitted to `strategies/<DIRECTIVE_NAME>/deployable/<PROFILE>/`:

| Artifact                    | Description                                      |
|-----------------------------|--------------------------------------------------|
| `equity_curve.csv`          | Per-bar portfolio equity path                    |
| `deployable_trade_log.csv`  | Accepted trades with lot sizes and realized PnL  |
| `summary_metrics.json`      | CAGR, Max DD, Final Equity, Accepted/Rejected    |
| `profile_comparison.json`   | Side-by-side metric comparison across profiles   |

Constraints:

- Must NOT modify `run_state.json`.
- Must NOT modify the ledger or manifest.
- Must NOT alter any Stage-1/2/3 artifacts.
- Must NOT change directive state.

Failure handling:

- Classify as `CAPITAL_WRAPPER_FAILURE`.
- Report exact error.
- Do NOT invalidate the completed directive.

### Step 9: Deployable Artifact Verification

Verify the outputs emitted in Step 8 are structurally sound before marking the run complete.

For each profile (`CONSERVATIVE_V1`, `AGGRESSIVE_V1`):

1. Confirm all 4 artifact files exist under `strategies/<DIRECTIVE_NAME>/deployable/<PROFILE>/`.
2. Load `summary_metrics.json` and confirm:
   - `final_equity = starting_capital + realized_pnl` (diff must be < $0.01)
   - `final_equity > 0`
3. Confirm `equity_curve.csv` has a `equity` column and minimum value > 0.
4. Confirm `deployable_trade_log.csv` row count matches `summary_metrics["total_accepted"]`.

// turbo

```
python -c "
import json, pandas as pd
from pathlib import Path

directive = '<DIRECTIVE_NAME>'
deploy_root = Path('strategies') / directive / 'deployable'

for prof in ['CONSERVATIVE_V1', 'AGGRESSIVE_V1']:
    d = deploy_root / prof
    assert d.exists(), f'Missing profile dir: {d}'
    m = json.loads((d / 'summary_metrics.json').read_text())
    diff = abs(m['final_equity'] - (m['starting_capital'] + m['realized_pnl']))
    assert diff < 0.01, f'[{prof}] Equity math mismatch: diff={diff}'
    assert m['final_equity'] > 0, f'[{prof}] Final equity is zero or negative'
    eq = pd.read_csv(d / 'equity_curve.csv')
    assert eq['equity'].min() > 0, f'[{prof}] Negative equity detected'
    tl = pd.read_csv(d / 'deployable_trade_log.csv')
    assert len(tl) == m['total_accepted'], f'[{prof}] Trade log count mismatch'
    print(f'[PASS] {prof}: final_equity={m[\"final_equity\"]:,.2f}, accepted={m[\"total_accepted\"]}')

print('All deployable artifact checks PASSED.')
"
```

Replace `<DIRECTIVE_NAME>` with the actual directive prefix before running.

On verification failure:

- Classify as `DEPLOYABLE_INTEGRITY_FAILURE`.
- Do NOT mark pipeline as complete.
- Report exact failing assertion.

On verification success:

- The deployable artifacts are structurally sound.
- Proceed to Step 10.

### Step 10: Robustness Suite Execution

After deployable artifacts are verified, run the full robustness evaluation suite
against **both** profiles' deployable artifacts.

This step is **observational only** — it reads deployable artifacts and produces
a markdown research report. It does NOT modify any pipeline state, directive state,
ledger, or manifest.

**10a. Conservative Profile:**

// turbo

```
python tools/evaluate_robustness.py <DIRECTIVE_NAME> --profile CONSERVATIVE_V1 --suite full
```

**10b. Aggressive Profile:**

// turbo

```
python tools/evaluate_robustness.py <DIRECTIVE_NAME> --profile AGGRESSIVE_V1 --suite full
```

Replace `<DIRECTIVE_NAME>` with the actual strategy prefix before running.

Outputs emitted (per profile):

| Location | File |
|---|---|
| `strategies/<DIRECTIVE_NAME>/ROBUSTNESS_<DIRECTIVE_NAME>_<PROFILE>.md` | Strategy root (primary copy) |
| `outputs/reports/ROBUSTNESS_<DIRECTIVE_NAME>_<PROFILE>.md` | Archive copy |

Report sections (14 total):

1. Edge Metrics Summary
2. Tail Contribution
3. Tail Removal
4. Sequence Monte Carlo (500 runs)
5. Reverse Path Test
6. Rolling 1-Year Window + Year-Wise PnL + Monthly Heatmap
7. Drawdown Diagnostics
8. Streak Analysis
9. Friction Stress Test
10. Directional Robustness
11. Early/Late Split
12. Symbol Isolation Stress
13. Per-Symbol PnL Breakdown
14. Block Bootstrap (100 runs)

Constraints:

- Must NOT modify `run_state.json`.
- Must NOT modify the ledger or manifest.
- Must NOT alter any pipeline artifacts.
- Must NOT change directive state.
- Must NOT invoke Stage1, indicator recomputation, or pipeline replay.
- Consumes ONLY: `deployable_trade_log.csv`, `equity_curve.csv`, `summary_metrics.json`.

Failure handling:

- Classify as `ROBUSTNESS_EVALUATION_FAILURE`.
- Report exact error.
- Do NOT invalidate the completed directive.

On success:

- Report the path to both generated robustness reports.
- The directive is fully complete end-to-end.

### System Contract

The system is: Deterministic, Ledger-authoritative, Append-only, Fail-fast, Non-mutating.  
Execution without compliance validation is prohibited.  
Capital Wrapper output is a deterministic, read-only derivation from Stage-1 artifacts.  
Deployable artifacts are non-authoritative over pipeline state and governance structures.  
Robustness reports are observational research artifacts with no governance authority.
