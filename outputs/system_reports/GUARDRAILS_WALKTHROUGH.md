The TradeScan pipeline has been hardened with six operational guardrails and an authoritative **Preflight Check** workflow to prevent filesystem drift, ensure lifecycle consistency, and protect system-critical artifacts.

## 0. Pipeline Preflight Check

Before running any pipeline directive, operators should execute the preflight diagnostic to ensure the environment is safe.

**Command**: `/pipeline_preflight.workflow` (or `python tools/system_preflight.py`)

This check performs a deep audit of:
- **Project Structure**: Ensures all critical root folders exist.
- **Run Containers**: Validates schema and physical presence of core artifacts.
- **Manifest Integrity**: Re-verifies every hash for completed runs at the starting line.
- **Registry Alignment**: Detects `DISK_NOT_IN_REGISTRY` or `REGISTRY_RUN_MISSING_ON_DISK` drifts.
- **Portfolio Health**: Confirms all referenced runs are physically available and valid.

## 1. Implemented Guardrails

| Guardrail | Stage | Component | Description |
| :--- | :--- | :--- | :--- |
| **Run Schema Enforcement** | Stage 0.1 | `run_pipeline.py` | Verifies `data/`, `manifest.json`, and `run_state.json` exist for every run. Faulty containers are moved to `quarantine/runs/`. |
| **Registry Consistency Gate** | Stage 0.2 | `run_pipeline.py` | Performs a lightweight dry-run reconciliation. Halts with explicit `DISK_NOT_IN_REGISTRY` or `REGISTRY_RUN_MISSING_ON_DISK` warnings. |
| **Strategy Directory Guard** | Stage 0.3 | `run_pipeline.py` | Detects untracked files or directories (missing metadata) in `strategies/`. Prevents manual drift. |
| **Startup Manifest Gate** | Stage 0.4 | `run_pipeline.py` | **[NEW]** Physically re-verifies every artifact hash in `runs/` against its `manifest.json` at startup. Halts on corruption. |
| **Manifest Integrity Rule** | Stage 3A | `stage_symbol_execution.py`| Strictly requires and hashes 4 core artifacts: `tradelevel`, `standard`, `equity_curve`, and `batch_summary`. |
| **Dependency Guard** | Stage 4 | `stage_portfolio.py` | Verifies that all runs referenced in a portfolio exist in both the registry and the `runs/` directory before evaluation. |
| **Cleanup Safety Boundary** | Admin | `cleanup_reconciler.py` | Restricts physical deletions to `runs/` and `backtests/` subfolders within the project root. Explicitly forbids system folders. |

## 2. Verification Results

### Automated Tests
- **Startup Protection**: [test_guardrails_startup.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/tests/test_guardrails_startup.py) verified quarantine logic, registry drift diagnostics, and manifest corruption gates.
- **Integrity Baseline**: [test_integrity_guards.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/test_integrity_guards.py) confirmed manifest freeze and partial run handling are still operational.

```text
Ran 6 tests in 0.062s
OK (test_guardrails_startup.py)
...
[DRIFT] DISK_NOT_IN_REGISTRY: ['RUN_DISK_ONLY']
[FATAL] Manifest Integrity Violations Detected: Hash mismatch for results_tradelevel.csv
```

## 3. Physical Layout Status
The system is now "Self-Healing" at the startup layer:
1. Invalid runs are automatically isolated.
2. Registry drift is detected *before* state-mutating code runs.
3. Portfolio dependencies are validated at the physical layer.

### Diagnostic Workflow
The preflight check is designed to be **read-only**. It identifies "RED" or "YELLOW" states that must be addressed manually or via automated quarantine before the pipeline is allowed to proceed.

```text
TRADE_SCAN PREFLIGHT CHECK
--------------------------
RUNS        GREEN
REGISTRY    GREEN
PORTFOLIOS  GREEN
ARCHIVE     GREEN
GUARDRAILS  GREEN

OVERALL STATUS: GREEN
++ Pipeline safe to run.
```

**Conclusion**: The pipeline architecture is now fully protected against the manual drift and structural gaps identified during the audit. The new preflight workflow ensures that no execution starts until the system state is verified as healthy.
