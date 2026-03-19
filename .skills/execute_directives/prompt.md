## Core Execution Workflow (The Golden Path)

This workflow executes directives in `backtest_directives/INBOX/` to produce authoritative **Candidates**.

### Prerequisites
- Directive YAML file(s) in `backtest_directives/INBOX/`
- AGENT.md (Failure Playbook) exists at project root

---

### Step 0: Directive Admission Gate

Before provisioning, you MUST verify data coverage and administrative alignment.

1.  **Temporal Coverage**: Verify `MASTER_DATA` timestamps cover the directive range (`avail_start <= req_start` AND `avail_end >= req_end`).
2.  **Optional Admission Pre-checks**: The following tools run automatically inside `run_pipeline.py`, but can be used for manual pre-validation:
    ```bash
    python tools/canonicalizer.py backtest_directives/INBOX/<DIRECTIVE_ID>.txt
    python tools/namespace_gate.py backtest_directives/INBOX/<DIRECTIVE_ID>.txt
    python tools/sweep_registry_gate.py backtest_directives/INBOX/<DIRECTIVE_ID>.txt
    ```

3.  **Optional Maintenance Check**: If workspace drift is suspected, run the reconciler from the **System Maintenance Workflow** to ensure the `runs/` directory is aligned with `run_registry.json`.

### Step 1: Provision-Only Validation

Execute provisioning to generate the strategy skeleton and verify imports.

// turbo

```bash
python tools/run_pipeline.py --all --provision-only
```

*Halt if `PROVISION_REQUIRED` is returned.*

### Step 2: Strategy Admission Gate

Classify the implementation mode based on the directive and existing code:
- **GENESIS_MODE**: New strategy. Implement exclusively from directive parameters.
- **PATCH_MODE**: Variation of parent (`_PXX` where XX > 00). Replicate logic from `_P00`.
- **CLONE_MODE**: Logic comparison. Copy code from original strategy exactly.

### Step 3: Human Strategy Review & Approval

1. Present `strategies/<NAME>/strategy.py` to the user for review.
2. **Approval Required**: The agent MUST NOT proceed without an explicit `APPROVED` response.
3. Verify the `# --- STRATEGY SIGNATURE ---` markers are present in the code.

### Step 4: Warmup Verification Test

Perform a regression test to ensure indicators are correctly initialized.

// turbo

```bash
python tools/tests/test_warmup_extension.py
```

*Do NOT proceed if any test fails.*

### Step 5: Full Pipeline Execution

After human approval, launch the multi-stage backtest.

// turbo

```bash
python tools/run_pipeline.py --all
```

*Monitor Stages 1-4. On failure, refer to **Step 5: Failure Handling** below.*

### Step 6: Capital Wrapper Execution
Simulate equity paths for `CONSERVATIVE_V1`, `DYNAMIC_V1`, and `FIXED_USD_V1`.

> [!IMPORTANT]
> **DATA GUARD**: The wrapper MUST run after Stage-4 completes.
> Verify `backtests/<RUN_ID>/raw/results_tradelevel.csv` exists before execution.

// turbo

```bash
python tools/capital_wrapper.py <DIRECTIVE_NAME>
```

### Step 7: Candidate Promotion

Perform the final quality filter and migrate passing runs to `candidates/`.

// turbo

```bash
python tools/filter_strategies.py
```

**Immediately report results:**

```text
=== CANDIDATE PROMOTION REPORT ===
Total strategies evaluated : <N>
Passed criteria            : <N>
Newly promoted this run    : <N>
Physically migrated        : <N>
===================================
```

**STOP — Mission Complete.**

---

## Appendix A: Failure Handling & Playbook
On ANY failure:
1.  Classify per `AGENT.md` failure playbook.
2.  Report exact failure class (e.g., `SCHEMA_VIOLATION`, `EXECUTION_ERROR`).
3.  Do NOT attempt silent repairs. Report to user immediately.

## Appendix B: Protected Infrastructure Policy
The agent MUST NOT modify the following without an **implementation plan** and **user approval**:
- `tools/*.py`, `engines/*.py`, `governance/*.py`, `vault/**`, `.agents/workflows/*.md`.

## Appendix C: System Contract
- Deterministic, Ledger-authoritative, Append-only, Fail-fast.
- Post-pipeline analysis (Robustness, Portfolios) is conducted via `portfolio-research.md`.
- System hygiene (Cleanup, Formatting) is conducted via `system-maintenance.md`.
