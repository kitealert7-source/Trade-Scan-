# Log Failure Audit Report

## Overview
This audit analyzes **34 historically failed/quarantined runs**. 
Because python tracebacks from hard-crashes are printed to STDOUT rather than preserved in the individual run folders, failure categories were forensically reconstructed by analyzing the **artifact footprint** (which files were successfully generated before the crash) of the quarantined runs.

---

## 1. Pre-Snapshot Failure (Headless Runs)
* **Count:** 27 runs
* **Primary Directives Affected:** S14 (18x), S13 (6x), S01 (2x)
* **Footprint:** Folder contains `run_state.json` (IDLE/FAILED) but is missing `strategy.py`, `data/`, and all CSVs.
* **Root Cause:** The `BootstrapController` eagerly provisions the run states and folders *before* `PreflightStage` executes. If Preflight validation fails (e.g., schema violation, missing indicator), the pipeline halts violently. These initialized folders are left stranded empty until `cleanup_reconciler.py` sweeps them into Quarantine.
* **Guardrail Improvement:** **Atomic Run Provisioning.** Shift Run-State Initialization to occur *after* `PreflightStage` successfully passes. Alternatively, if Preflight fails, the orchestrator should immediately garbage-collect the empty run states rather than relying on a delayed asynchronous sweep.

## 2. Engine Launch Failure (Instant Crash)
* **Count:** 5 runs
* **Footprint:** Folder contains a copied `strategy.py`, but no `data/` subdirectory exists.
* **Root Cause:** The orchestrator reached Stage-1 and snapped the strategy, but the backtest engine crashed *instantly* upon launch (e.g., syntax error in the strategy file, module import failure, or engine arguments mismatch) before it could even scaffold its output directory.
* **Guardrail Improvement:** **Traceback Registry Persistence.** The `run_skill("backtest_execution")` wrapper must trap raw `Stderr` or tracebacks from the engine subprocess and explicitly flush them to a permanent `crash_trace.log` file inside the run directory before raising the python Exception. Currently, these errors only live in the ephemeral console buffer.

## 3. Engine Execution Failure / NO_TRADES
* **Count:** 2 runs
* **Primary Directives Affected:** S14 (1x), S04 (1x)
* **Footprint:** Folder contains `strategy.py` and an empty `data/` folder, but no `results_tradelevel.csv`.
* **Root Cause:** The engine successfully launched and researched the dataset, but the strategy logic yielded exactly **0 trades**. Because no trades occurred, the engine gracefully exited without writing the expected `results_tradelevel.csv`, causing the Orchestrator's Stage-1 mandatory artifact gate to trigger a `[FATAL] Missing artifact` error.
* **Guardrail Improvement:** **Explicit NO_TRADES Artifact.** The research engine must be updated to output an explicit empty file or marker (e.g., `results_tradelevel.csv` with just headers, or `status_no_trades.json`) when a session genuinely yields 0 trades. The orchestrator can then detect this marker and gracefully close the run as `COMPLETE_NO_TRADES` rather than treating it as a violent crash.
