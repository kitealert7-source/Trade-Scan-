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

### Step 1.5: Strategy Generation Mode Classification

Before provisioning, classify each directive by checking whether an implementation exists:

**If `strategies/<STRATEGY_NAME>/strategy.py` EXISTS → CLONE_MODE**

- Log: `[MODE] CLONE_MODE: Existing strategy found`
- Modifications to existing code are permitted
- Must pass semantic coverage gate after any changes

**If `strategies/<STRATEGY_NAME>/strategy.py` DOES NOT EXIST → GENESIS_MODE**

- Log: `[MODE] GENESIS_MODE: New strategy required`
- Implement exclusively from the directive's declared parameters

**GENESIS_MODE — Allowed:**

- Structural skeleton reuse (class definition pattern, `__init__` shape)
- Method signature reuse (`prepare_indicators`, `check_entry`, `check_exit` signatures)
- Base class pattern reuse (FilterStack instantiation, indicator import pattern)

**GENESIS_MODE — Forbidden:**

- Behavioral logic borrowing (copying entry/exit condition logic from another strategy)
- Cross-family entry/exit logic reuse (e.g. adapting ORB breakout logic for a mean-reversion directive)
- Parameter mapping inference (guessing how directive parameters map to code by looking at how a different strategy mapped its parameters)
- Engine infrastructure patching to accommodate the new strategy

If GENESIS_MODE implementation fails or semantic validation fails → **halt and report**. Do NOT attempt silent fixes.

### Step 1.75: Directive Canonicalization Gate

Before provisioning, validate the directive's structural form against the frozen canonical schema:

// turbo

```
python tools/canonicalizer.py backtest_directives/active/<DIRECTIVE_ID>.txt
```

If the directive is already canonical: `[PASS]` — proceed to Step 2.

If structural drift is detected:

- The tool outputs a unified diff and writes the corrected YAML to `/tmp/<DIRECTIVE_ID>_canonical.yaml`.
- Review the diff. If correct, overwrite the original:

```
python tools/canonicalizer.py backtest_directives/active/<DIRECTIVE_ID>.txt --execute
```

- If the diff is incorrect, fix the directive manually.

> [!CAUTION]
> **SCHEMA FREEZE**: The canonical schema is frozen. Unknown keys, misplaced blocks,
> and legacy field names will cause a HARD FAIL. The canonicalizer does NOT invent
> defaults, guess structure, or auto-fix values. It only moves, renames, or reorders
> keys according to the explicit migration/misplacement tables.

> [!IMPORTANT]
> This gate also runs automatically inside `run_pipeline.py` (Stage -0.25).
> If executed via `--all`, the pipeline will halt and exit on structural drift.
> The standalone CLI is provided for pre-checking directives before pipeline runs.

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

> [!CAUTION]
> **APPROVAL CHECKPOINT**: The agent MUST NOT proceed to Step 4 without
> the user's explicit `APPROVED` response. No implicit approval is valid.
> The agent MUST NOT auto-implement strategy logic and then immediately
> execute the pipeline. Each action (implement → review → approve → execute)
> is a separate checkpoint.

### Step 4: Full Pipeline Execution

After human approval, execute the full pipeline:

```text
python tools/run_pipeline.py --all
```

If a directive is in FAILED state, it must first be reset using the governance tool:

```text
python tools/reset_directive.py <DIRECTIVE_ID> --reason "<justification>"
```

To resume at Stage-4 without re-running Stages 0-3 (only from FAILED or PORTFOLIO_COMPLETE):

```text
python tools/reset_directive.py <DIRECTIVE_ID> --reason "<justification>" --to-stage4
```

> [!IMPORTANT]
> `--force` has been removed. All state resets require a mandatory justification
> logged to `governance/reset_audit_log.csv`. Full resets also clean associated
> per-symbol run states. The agent MUST NOT call `reset_directive.py`
> autonomously — only a human may authorize a reset.

Monitor execution through all stages:

- Stage-0: Preflight (root-of-trust + engine + tools integrity)
- Stage-0.5: Semantic Validation + Admission Gate
- Stage-0.55: Semantic Coverage Check (all directive params referenced in code)
- Stage-0.75: Dry-Run Validator (real ContextView, not mocks)
- Stage-1: Execution (per symbol)
- Stage-2: Compilation
- Stage-3: Aggregation + Snapshot + Manifest
- Stage-4: Portfolio Evaluation + Ledger Gate

### Step 5: Failure Handling

On ANY failure:

1. Classify per `AGENT.md` failure playbook.
2. Report the exact failure class from: PROVISION_REQUIRED, SCHEMA_VIOLATION, HOLLOW_STRATEGY_DETECTED, ARTIFACT_MISSING, STATE_TRANSITION_INVALID, EXECUTION_ERROR, DRYRUN_CRASH, STAGE_3_CARDINALITY_MISMATCH, STAGE_4_LEDGER_MISMATCH, SNAPSHOT_INTEGRITY_MISMATCH, MANIFEST_TAMPER_DETECTED, FILTERSTACK_ARCHITECTURAL_VIOLATION, INDICATOR_IMPORT_MISMATCH, TRADE_PAYLOAD_SCHEMA_VIOLATION, INDICATOR_SERIES_OVERWRITE, PREFLIGHT_FAILURE, DATA_LOAD_FAILURE, REPORT_GENERATION_FAILURE, CAPITAL_WRAPPER_FAILURE, DEPLOYABLE_INTEGRITY_FAILURE, ROBUSTNESS_EVALUATION_FAILURE.
3. Do NOT attempt automatic repair.
4. Do NOT retry without addressing root cause.
5. Do NOT modify strategy code without human approval.
6. Do NOT modify any Protected Infrastructure file (see below) without presenting an implementation plan and receiving explicit user approval.
7. Report the failure to the user immediately. Do NOT chain multiple fix attempts without user visibility.

> [!CAUTION]
> **NO SILENT FIX CHAINS**: If a failure requires engine code changes,
> the agent MUST stop, present the diagnosis and proposed fix to the user,
> and wait for explicit approval before editing any file.

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
| `equity_curve.png`          | Visual equity curve chart (human-readable)       |
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

1. Confirm all 5 artifact files exist under `strategies/<DIRECTIVE_NAME>/deployable/<PROFILE>/`.
2. Load `summary_metrics.json` and confirm:
   - `final_equity = starting_capital + realized_pnl` (diff must be < $0.01)
   - `final_equity > 0`
3. Confirm `equity_curve.csv` has a `equity` column and minimum value > 0.
4. Confirm `equity_curve.png` exists and has non-zero file size.
5. Confirm `deployable_trade_log.csv` row count matches `summary_metrics["total_accepted"]`.

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
python -m tools.robustness.cli <DIRECTIVE_NAME> --profile CONSERVATIVE_V1 --suite full
```

**10b. Aggressive Profile:**

// turbo

```
python -m tools.robustness.cli <DIRECTIVE_NAME> --profile AGGRESSIVE_V1 --suite full
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

### Protected Infrastructure Policy

The following paths are classified as **Protected Infrastructure**.
The agent MUST NOT modify any file under these paths without:

1. Presenting an **implementation plan** describing the exact change, rationale, and affected components.
2. Receiving explicit **user approval** (`APPROVED`) before editing.
3. Re-running relevant validation after the change.

**Protected Paths:**

| Path Pattern | Scope |
|---|---|
| `tools/*.py` | Pipeline scripts, validators, provisioners |
| `tools/*.json` | Guard-layer manifest, tool configs |
| `engines/*.py` | FilterStack, execution engines |
| `engine_dev/**/*.py` | Vaulted engine versions |
| `engine_dev/**/*.json` | Engine manifests |
| `governance/**/*.py` | Preflight, SOP enforcement |
| `governance/SOP/*.md` | Governing SOPs |
| `vault/**` | Root-of-trust bindings, recovery snapshots |
| `.agents/workflows/*.md` | Workflow definitions |

**Permitted without approval:**

| Path Pattern | Scope |
|---|---|
| `strategies/<NAME>/strategy.py` | Strategy logic (still requires Step 3 review) |
| `backtest_directives/active/*.txt` | Directive files (user-owned content) |
| `/tmp/*` | Scratch scripts |

> [!IMPORTANT]
> This policy exists because engine infrastructure changes have cascading
> effects across all directives. A single unreviewed change can invalidate
> prior baselines, break governance gates, or silently alter execution semantics.

### System Contract

The system is: Deterministic, Ledger-authoritative, Append-only, Fail-fast, Non-mutating.  
Execution without compliance validation is prohibited.  
Capital Wrapper output is a deterministic, read-only derivation from Stage-1 artifacts.  
Deployable artifacts are non-authoritative over pipeline state and governance structures.  
Robustness reports are observational research artifacts with no governance authority.
