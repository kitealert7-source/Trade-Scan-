The TradeScan pipeline has been hardened with six operational guardrails and an authoritative **Preflight Check** workflow to prevent filesystem drift, ensure lifecycle consistency, and protect system-critical artifacts.

## 0. Pipeline Preflight Check

Before running any pipeline directive, operators should execute the preflight diagnostic to ensure the environment is safe.

**Command**: `/pipeline_preflight.workflow` (or `python tools/system_preflight.py`)

This check performs a deep audit of:
- **Project Structure**: Ensures all critical root folders exist.
- **Run Containers**: Validates schema and physical presence of core artifacts.
- **Manifest Integrity**: Re-verifies every hash for completed runs at the starting line.
- **Registry Alignment**: Tier-aware resolution across `runs/`, `sandbox/`, and `quarantine/`. Detects orphans, truly missing runs, and quarantined-but-lost entries.
- **Data Availability**: Asserts that historical data fully covers requested date range.
- **Execution Contract**: **[NEW]** Verifies every enabled strategy in `TS_Execution/portfolio.yaml` has `strategy.py`, `portfolio_evaluation/`, and passes `signal_schema.validate(_schema_sample())`.

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
| **Reconciler Auto-Clean** | Admin | `system_registry.py` | After marking runs invalid during reconciliation, automatically removes stale `constituent_run_ids` from all `portfolio_metadata.json` files before the Portfolio Dependency Check fires. Prevents recurring `[FATAL] Consistency Violation` errors on subsequent pipeline runs. |
| **Atomic Directive Reset** | Admin | `reset_directive.py` | On full reset to `INITIALIZED`, deletes the directive's run folder in **both** `TradeScan_State/runs/<DIRECTIVE_ID>/` (canonical state) **and** `Trade_Scan/runs/<DIRECTIVE_ID>/` (project-local planner registry written by `tools/orchestration/run_planner.py` when `context.project_root` is set). Both folders contain a `run_registry.json`; `ensure_registry()` preserves existing run state by run_id, so a stale `COMPLETE` left in the project-local copy silently causes Stage-1 to skip on the next attempt while the global state machine reports a downstream state mismatch. Partial cleanup (one location only) is explicitly forbidden — regression pinned by `tests/test_reset_directive_dual_registry_cleanup.py` (added 2026-05-11 after a re-run incident on `65_BRK_XAUUSD_5M_PSBRK_S02_V1_P01`). |
| **Execution Contract** | Preflight | `system_preflight.py` | **[NEW]** For every enabled strategy in `TS_Execution/portfolio.yaml`: verifies `strategy.py` exists, `portfolio_evaluation/` exists, and `_schema_sample()` passes `signal_schema.validate()`. Blocks pipeline if any deployed strategy would fail at TS_Execution startup. |
| **Execution Shield** | Cleanup | `lineage_pruner.py` | **[NEW]** `build_execution_shield()` reads `portfolio.yaml` and unconditionally blocks quarantine of any deployed strategy. `execution_pid_exists()` blocks cleanup while TS_Execution is running (PID + heartbeat two-layer check). |
| **Quarantine Registry Sync** | Cleanup | `lineage_pruner.py` | **[NEW]** `batch_update_registry_status()` atomically marks quarantined runs as `status: "quarantined"` in `run_registry.json` after all moves complete. Prevents registry–filesystem divergence. |

## 3. Verification Results

### Automated Tests
- **Startup Protection**: [test_guardrails_startup.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/tests/test_guardrails_startup.py) verified quarantine logic, registry drift diagnostics, and manifest corruption gates.
- **Integrity Baseline**: [test_integrity_guards.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/tests/test_integrity_guards.py) confirmed manifest freeze and partial run handling are still operational.

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

**2026-03-19 additions:**
5. Reconciler auto-clean eliminates the manual step of clearing stale `constituent_run_ids` from `portfolio_metadata.json` files after runs are invalidated.
6. Directive reset is now deterministic and atomic — the entire directive-level run folder is deleted, preventing phantom state from persisting across reset boundaries.

**2026-04-02 additions (post-quarantine incident):**
7. Execution Contract check in preflight verifies every deployed strategy in `portfolio.yaml` has `strategy.py`, `portfolio_evaluation/`, and a valid `_schema_sample()`. Detects post-cleanup breakage before TS_Execution restart.
8. Execution Shield in `lineage_pruner.py` unconditionally blocks quarantine of deployed strategies. Running-process guard blocks cleanup while TS_Execution is active.
9. Quarantine Registry Sync atomically updates `run_registry.json` after quarantine moves, preventing registry–filesystem divergence.
10. Tier-aware run resolution in preflight correctly locates runs across `runs/`, `sandbox/`, and `quarantine/` — eliminates false positives from sandbox routing.
