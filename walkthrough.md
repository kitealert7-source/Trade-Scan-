
# Multi-Asset Batch Execution (v4) Walkthrough

## Overview
Implemented and verified the **Multi-Asset Batch Execution System (v4)** across all pipeline stages.
The system now supports independent processing of multiple symbols from a single directive, preserving isolation and ensuring authoritative lineage.

## Key Features Implemented

### 1. Stage-1: Batch Execution (`run_stage1.py`)
- **Dynamic Multi-Asset Processing**: Iterates through `Symbols` list in directive.
- **Isolation**: Each symbol runs independently. Failure in one does not block others.
- **Canonical Linage**: Run ID includes resolved Configuration (Timeframe, Dates, Broker).
- **Metadata**: Content Hash and Lineage String persisted in `metadata/run_metadata.json`.

### 2. Governance: Preflight Consolidation (`preflight.py`)
- **Single Authority**: Consolidated all preflight logic into `governance/preflight.py`.
- **Batch-Aligned**: Validates global structure only; skips per-symbol data checks (delegated to Stage-1).
- **Consistent Hashing**: Imports Stage-1 hashing logic to ensure Preflight and Execution agree on Config Hash.
- **Deleted**: Removed redundant `run_preflight_script.py`.

### 3. Stage-2: Batch Scan Mode (`stage2_compiler.py`)
- **New Feature**: Added `--scan DIRECTIVE_NAME` mode.
- **Behavior**: Scans `backtests/` for folders matching `DIRECTIVE_NAME_*`.
- **Validation**: Compiles only valid run folders (with metadata/results).
- **Timeframe Fix**: Removed hardcoded 4H assumption. Now dynamically calculates `bars_per_day` from empirical trade duration or metadata fallback.
- **Backward Compatibility**: `python tools/stage2_compiler.py RUN_FOLDER` still works.

## Verification Results

### Test Directive: `TEST_BATCH.txt`
- **Symbols**: `AUDUSD`, `GBPUSD`.
- **Broker**: `OctaFx`.

### 1. Preflight
```
[SCAN] Found 2 valids runs
PASSED: ALLOW_EXECUTION
Canonical Hash: bbbea9be
```

### 2. Stage-1 Execution
- **Run 1**: `backtests/TEST_BATCH_AUDUSD` (Success, RunID `469b40f9`)
- **Run 2**: `backtests/TEST_BATCH_GBPUSD` (Success, RunID `16edc164`)

### 3. Stage-2 Compilation
Command: `python tools/stage2_compiler.py --scan TEST_BATCH`
Output:
```
[SCAN] Found 2 valid runs for 'TEST_BATCH'
>>> Compiling: TEST_BATCH_AUDUSD ... [OK]
>>> Compiling: TEST_BATCH_GBPUSD ... [OK]
```
Artifacts Created:
- `backtests/TEST_BATCH_AUDUSD/AK_Trade_Report_TEST_BATCH_AUDUSD.xlsx`
- `backtests/TEST_BATCH_GBPUSD/AK_Trade_Report_TEST_BATCH_GBPUSD.xlsx`

### 4. Robustness Verification (`verify_batch_robustness.py`)
- **Canonical Stability**: Confirmed Hash `6d4ed399` remains identical after reordering JSON keys.
- **Sensitivity**: Confirmed Hash changes when parameter value changes.
- **Failure Isolation**: Confirmed `INVALID_SYMBOL` fails gracefully while `AUDUSD` continues to process in the same batch.

### 5. Master Filter Update
- **Added**: `TEST_BATCH_AUDUSD` and `TEST_BATCH_GBPUSD` to `Strategy_Master_Filter.xlsx`.

## Conclusion
The pipeline is now fully capable of Multi-Asset Batch Execution with complete governance compliance.
