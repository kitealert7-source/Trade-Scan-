# STATE_ROOT Infrastructure Separation Report (Phase-2 Step-1)
Date: 2026-03-13

## Objective
The goal was to decouple research state (runs, registries, strategies) from the code repository by introducing a centralized `STATE_ROOT` directory sibling to the repository.

## Implementation Details

### 1. Constants Module
**File**: `config/state_paths.py`
- Defined `PROJECT_ROOT`, `STATE_ROOT`, and various lifecycle directories (`RUNS_DIR`, `SANDBOX_DIR`, etc.).
- `STATE_ROOT` resolves to a sibling directory named `TradeScan_State`.
- Implemented `initialize_state_directories()` for automatic bootstrapping.

### 2. Orchestration Updates
**File**: `tools/run_pipeline.py`
- Injected `initialize_state_directories()` at startup.
- Updated guardrails (`enforce_run_schema`, `detect_strategy_drift`, `verify_manifest_integrity`) to use externalized paths.

**File**: `tools/pipeline_utils.py`
- Redirected `PipelineStateManager` and `DirectiveStateManager` to write to the external `RUNS_DIR`.

**File**: `tools/system_registry.py`
- Redirected the registry database and strategy provisioning paths to the state root.

### 3. Governance Alignment
- Regenerated `tools/tools_manifest.json` to authorize the new path constants and logic, ensuring no violation of the engine integrity self-tests.

## Verification Results
- **Bootstrapping**: Verified `TradeScan_State/` and its subdirectories are created outside the repo.
- **Redirection**: Confirmed that `run_pipeline.py` and all orchestration components (`run_planner.py`, `stage_symbol_execution.py`, `stage_portfolio.py`) correctly utilize the external state root.
- **Hygiene Test**: A trial run confirmed that NO `runs/` or `backtests/` directories are recreated in the repository root. All physical artifacts reside exclusively in `TradeScan_State/`.
- **Registry**: Confirmed `run_registry.json` is maintained in `TradeScan_State/registry/`.
- **Cleanup**: Legacy `runs/` and `backtests/` directories in the repository were purged.

## Status
**VERIFIED PERFECT SEPARATION** - Phase-2 Infrastructure is now fully isolated and orchestration-hardened.
