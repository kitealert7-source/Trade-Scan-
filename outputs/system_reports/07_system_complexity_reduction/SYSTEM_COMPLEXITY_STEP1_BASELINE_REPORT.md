# System Complexity Step-1 Baseline Report
**Date:** 2026-03-11  
**Purpose:** Freeze current behavior before architecture simplification/refactor.

## Scope Executed
Step 1 from `SYSTEM_COMPLEXITY_REFACTOR_PLAN.md` was executed:
- baseline capture for 3 representative scenarios
- non-regression checks defined and executed
- complexity snapshot frozen (size + control-flow density)
- core orchestrator/governance file hashes frozen

## Baseline Artifacts
Folder:
- `outputs/system_reports/baselines/STEP1_BASELINE_2026-03-11/`

Primary files:
- `baseline_manifest.json` (authoritative baseline snapshot)
- `baseline_manifest_historical.json` (historical full-run scenarios)
- `provision_only_snapshot.json` (provision-only runtime scenario)
- `provision_only_stdout.log`
- `provision_only_run_state_snapshot.json`
- `provision_only_audit_snapshot.log`
- `provision_only_directive_state_snapshot.json`
- `provision_only_directive_audit_snapshot.log`
- `non_regression_results.json`
- `check_01_provision_only_test.log`
- `check_02_registry_and_provisioner.log`

## Representative Scenarios Frozen
1. Single-symbol historical full pipeline
- Directive: `02_VOL_NAS100_1D_VOLEXP_ATRFILT_S02_V1_P00`
- Batch summary hash and run-state/audit hashes captured.

2. Multi-symbol historical full pipeline
- Directive: `01_MR_FX_1D_RSIAVG_TRENDFILT_S01_V1_P04`
- Batch summary hash and all 10 symbol run-state/audit hashes captured.

3. Provision-only runtime snapshot
- Source directive: `TEST_PROVISION_DF6A98B5` (ephemeral baseline run)
- Effective directive: `03_TREND_EURUSD_1D_RSIAVG_S01_V1_P00`
- Confirmed behavior tokens:
  - strategy provisioned message present
  - human review required message present
  - rerun without `--provision-only` message present
  - Stage-1 launch message absent
- Snapshot logs/state copied into baseline artifact folder.
- Temporary runtime artifacts were cleaned and sweep registry restored.

## Non-Regression Gate (Current)
Defined gate commands:
1. `PYTHONPATH=. pytest -q tests/test_provision_only_integration.py`
2. `pytest -q tests/test_sweep_registry_hash_compat.py tests/test_strategy_provisioner_compat.py`

Current status:
- both checks passing in baseline capture run (`non_regression_results.json`).

Note:
- `test_provision_only_integration.py` requires `PYTHONPATH=.` when run standalone in this environment.

## Complexity Snapshot (Frozen)
From baseline capture:
- `tools/run_pipeline.py`: 999 lines
- `tools/pipeline_utils.py`: 513 lines
- `governance/preflight.py`: 426 lines
- `tools/strategy_provisioner.py`: 294 lines
- `tools/convert_promoted_directives.py`: 431 lines
- `tools/sweep_registry_gate.py`: 419 lines
- `run_pipeline.py` `transition_to(...)` calls: 47
- `run_pipeline.py` `except` blocks: 37

## Ready-for-Refactor Decision
Step-1 baseline is complete.  
Refactor work can proceed with `baseline_manifest.json` as the non-regression reference.
