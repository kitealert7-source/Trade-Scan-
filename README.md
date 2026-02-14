# Trade\_Scan

Trade\_Scan is a read-only consumer of research-grade data.

* It supports human-directed research only
* It includes capital and broker-cost simulation for validation
* It has no execution, no live trading, and no automation authority
* Nothing is immutable unless explicitly frozen by humans







\# Multi-Asset Batch Execution (v4) Walkthrough



\## Overview

Implemented and verified the \*\*Multi-Asset Batch Execution System (v4)\*\* across all pipeline stages.

The system now supports independent processing of multiple symbols from a single directive, preserving isolation and ensuring authoritative lineage.



\## Key Features Implemented



\### 1. Stage-1: Batch Execution (`run\_stage1.py`)

\- \*\*Dynamic Multi-Asset Processing\*\*: Iterates through `Symbols` list in directive.

\- \*\*Isolation\*\*: Each symbol runs independently. Failure in one does not block others.

\- \*\*Canonical Linage\*\*: Run ID includes resolved Configuration (Timeframe, Dates, Broker).

\- \*\*Metadata\*\*: Content Hash and Lineage String persisted in `metadata/run\_metadata.json`.



\### 2. Governance: Preflight Consolidation (`preflight.py`)

\- \*\*Single Authority\*\*: Consolidated all preflight logic into `governance/preflight.py`.

\- \*\*Batch-Aligned\*\*: Validates global structure only; skips per-symbol data checks (delegated to Stage-1).

\- \*\*Consistent Hashing\*\*: Imports Stage-1 hashing logic to ensure Preflight and Execution agree on Config Hash.

\- \*\*Deleted\*\*: Removed redundant `run\_preflight\_script.py`.



\### 3. Stage-2: Batch Scan Mode (`stage2\_compiler.py`)

\- \*\*New Feature\*\*: Added `--scan DIRECTIVE\_NAME` mode.

\- \*\*Behavior\*\*: Scans `backtests/` for folders matching `DIRECTIVE\_NAME\_\*`.

\- \*\*Validation\*\*: Compiles only valid run folders (with metadata/results).

\- \*\*Timeframe Fix\*\*: Removed hardcoded 4H assumption. Now dynamically calculates `bars\_per\_day` from empirical trade duration or metadata fallback.

\- \*\*Backward Compatibility\*\*: `python tools/stage2\_compiler.py RUN\_FOLDER` still works.



\## Verification Results



\### Test Directive: `TEST\_BATCH.txt`

\- \*\*Symbols\*\*: `AUDUSD`, `GBPUSD`.

\- \*\*Broker\*\*: `OctaFx`.



\### 1. Preflight

```

\[SCAN] Found 2 valids runs

PASSED: ALLOW\_EXECUTION

Canonical Hash: bbbea9be

```



\### 2. Stage-1 Execution

\- \*\*Run 1\*\*: `backtests/TEST\_BATCH\_AUDUSD` (Success, RunID `469b40f9`)

\- \*\*Run 2\*\*: `backtests/TEST\_BATCH\_GBPUSD` (Success, RunID `16edc164`)



\### 3. Stage-2 Compilation

Command: `python tools/stage2\_compiler.py --scan TEST\_BATCH`

Output:

```

\[SCAN] Found 2 valid runs for 'TEST\_BATCH'

>>> Compiling: TEST\_BATCH\_AUDUSD ... \[OK]

>>> Compiling: TEST\_BATCH\_GBPUSD ... \[OK]

```

Artifacts Created:

\- `backtests/TEST\_BATCH\_AUDUSD/AK\_Trade\_Report\_TEST\_BATCH\_AUDUSD.xlsx`

\- `backtests/TEST\_BATCH\_GBPUSD/AK\_Trade\_Report\_TEST\_BATCH\_GBPUSD.xlsx`



\### 4. Robustness Verification (`verify\_batch\_robustness.py`)

\- \*\*Canonical Stability\*\*: Confirmed Hash `6d4ed399` remains identical after reordering JSON keys.

\- \*\*Sensitivity\*\*: Confirmed Hash changes when parameter value changes.

\- \*\*Failure Isolation\*\*: Confirmed `INVALID\_SYMBOL` fails gracefully while `AUDUSD` continues to process in the same batch.



\### 5. Master Filter Update

\- \*\*Added\*\*: `TEST\_BATCH\_AUDUSD` and `TEST\_BATCH\_GBPUSD` to `Strategy\_Master\_Filter.xlsx`.



\## Conclusion

The pipeline is now fully capable of Multi-Asset Batch Execution with complete governance compliance.



