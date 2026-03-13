---
description: Perform a comprehensive read-only system preflight check before any pipeline execution.
---

# TradeScan Pipeline Preflight Workflow

This workflow performs a comprehensive **read-only system preflight check** to detect operational mistakes, filesystem drift, or integrity violations before the pipeline starts.

> [!IMPORTANT]
> This workflow is **read-only**. It will never move files or modify the registry.

## Operator Workflow

1. **Run the preflight diagnostic**:
   `python tools/system_preflight.py`

2. **If status = GREEN or YELLOW**:
   `python tools/run_pipeline.py <DIRECTIVE_ID>`

3. **After pipeline completion**:
   Run the system health audit.

## Step 1 — Authoritative Diagnostic Sweep

Run the master preflight script to evaluate system health.

// turbo
`python tools/system_preflight.py`

## Step 1A — Project Structure Check

Verify the following directories exist:
- `runs/`
- `strategies/`
- `registry/`
- `archive/`
- `quarantine/`

If any are missing, restore them before running the pipeline.

## Step 2 — Evaluation Checklist

If the preflight script reports **RED**, follow these instructions:

1. **Run Container Schema Failures**
   - Inspect the reported `run_id` in `runs/`.
   - Ensure `data/`, `manifest.json`, and `run_state.json` are present.
   - If a run is genuinely invalid, let the pipeline auto-quarantine it at startup or move manually to `quarantine/runs/`.

2. **Registry Consistency Failures**
   - `DISK_NOT_IN_REGISTRY`: A run was created but not logged. Wait for auto-reconciliation or check if it was a manual addition.
   - `REGISTRY_RUN_MISSING_ON_DISK`: A registry entry exists without a folder. Verify if it was accidentally deleted.

3. **Manifest Integrity Violations**
   - **RED ALERT**: This indicates manual tampering or filesystem corruption.
   - Do NOT run the pipeline until the mismatched files are restored or the run is archived.

4. **Portfolio Dependency Failures**
   - A strategy requires a run that is missing.
   - Restore the run from `BACKUPDATA/` or mark the portfolio as stale.

2.5. **Data Availability Gate (Temporal Assertion)**
   - `DATA_RANGE_INSUFFICIENT`: The local historical data does not fully cover the `START_DATE` to `END_DATE` requested.
   - **RED ALERT**: Do NOT bypass. Locate missing data files or adjust the directive dates to match available coverage.

3. **Strategy Drift Warning (YELLOW)**

If the script reports **YELLOW**:

1. Inspect `strategies/` for unexpected files (e.g., `temp.csv`, `old_metrics.json`).
2. Remove or move untracked files to maintain directory hygiene.

## Step 4 — Guardrail Status Verification

Ensure all operational guards remain present in `tools/run_pipeline.py`. If any are reported missing, revert the code or re-install the guards immediately.

## Step 5 — Final Decision

- **GREEN**: Continue to `python tools/run_pipeline.py <DIRECTIVE_ID>`.
- **YELLOW**: Review warnings, then continue.
- **RED**: **HALT**. Resolve all integrity issues before execution.
