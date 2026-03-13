The TradeScan pipeline has been hardened with six operational guardrails and an authoritative **Preflight Check** workflow to prevent filesystem drift, ensure lifecycle consistency, and protect system-critical artifacts.

## 0. Pipeline Preflight Check

Before running any pipeline directive, operators should execute the preflight diagnostic to ensure the environment is safe.

**Command**: `/pipeline_preflight.workflow` (or `python tools/system_preflight.py`)

This check performs a deep audit of:
- **Project Structure**: Ensures all critical root folders exist.
- **Run Containers**: Validates schema and physical presence of core artifacts.
- **Manifest Integrity**: Re-verifies every hash for completed runs at the starting line.
- **Registry Alignment**: Detects `DISK_NOT_IN_REGISTRY` drifts.
- **Data Availability**: **[NEW]** Asserts that historical data fully covers requested date range.

## 1. Operator Lifecycle

The intended daily workflow for TradeScan operators is as follows:

1. **Run Preflight**: `python tools/system_preflight.py`
2. **Review Status**:
   - **GREEN**: Safe to proceed.
   - **YELLOW**: Warning (e.g. drift in `strategies/`). Review content before proceeding.
   - **RED**: **HALT**. Resolve integrity violations (e.g. manifest hash mismatch) before execution.
3. **Execute Pipeline**: `python tools/run_pipeline.py <DIRECTIVE_ID>`
4. **Post-Run Audit**: Review registry and manifest to confirm completion.

## 2. Implemented Guardrails

| Guardrail | Stage | Component | Description |
| :--- | :--- | :--- | :--- |
| **Run Schema Enforcement** | Stage 0.1 | `run_pipeline.py` | Verifies `data/`, `manifest.json`, and `run_state.json` exist for every run. Faulty containers are moved to `quarantine/runs/`. |
| **Registry Consistency Gate** | Stage 0.2 | `run_pipeline.py` | Performs a lightweight dry-run reconciliation. Halts with explicit `DISK_NOT_IN_REGISTRY` or `REGISTRY_RUN_MISSING_ON_DISK` warnings. |
| **Strategy Directory Guard** | Stage 0.3 | `run_pipeline.py` | Detects untracked files or directories (missing metadata) in `strategies/`. Prevents manual drift. |
| **Startup Manifest Gate** | Stage 0.4 | `run_pipeline.py` | **[NEW]** Physically re-verifies every artifact hash in `runs/` against its `manifest.json` at startup. Halts on corruption. |
| **Manifest Integrity Rule** | Stage 3A | `stage_symbol_execution.py`| Strictly requires and hashes 4 core artifacts: `tradelevel`, `standard`, `equity_curve`, and `batch_summary`. |
| **Dependency Guard** | Stage 4 | `stage_portfolio.py` | Verifies that all runs referenced in a portfolio exist in both the registry and the `runs/` directory before evaluation. |
| **Data Availability Gate** | Stage 0.5 | `preflight.py` | **[NEW]** Asserts that research data fully covers the directive's `START_DATE` and `END_DATE`. Prevents silent truncation. |
| **Cleanup Safety Boundary** | Admin | `cleanup_reconciler.py` | Restricts physical deletions to `runs/` and `backtests/` subfolders within the project root. Explicitly forbids system folders. |

## 3. Verification Results

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

## 4. Physical Layout Status
The system is now "Self-Healing" at the startup layer:
1. Invalid runs are automatically isolated (quarantined).
2. Registry drift is detected *before* state-mutating code runs.
3. Portfolio dependencies are validated at the physical layer.

**Conclusion**: The pipeline architecture is now fully protected against the manual drift and structural gaps identified during the audit. The new preflight workflow ensures that no execution starts until the system state is verified as healthy.
