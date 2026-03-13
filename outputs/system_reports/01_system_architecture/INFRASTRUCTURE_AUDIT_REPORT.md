# TradeScan Infrastructure Audit Report

This report summarizes the audit of the TradeScan pipeline infrastructure against the Phase-2 lifecycle implementation requirements.

## Summary Table

| Capability | Status | Notes |
| :--- | :--- | :--- |
| **1. Run Container Contract** | Already implemented | Verified `runs/<run_id>/data/`, `manifest.json`, and `run_state.json` in completed runs. |
| **2. Directive Hashing** | Partially implemented | Hashing logic exists (`pipeline_utils.py`), but the `run_registry.json` currently stores directive IDs in the `directive_hash` field. |
| **3. Pipeline Version Tracking** | Missing | `engine_version` is used in orchestration but not explicitly recorded as a first-class run artifact. |
| **4. Sandbox / Candidate Lifecycle** | Partially implemented | `run_registry.json` includes `tier` (defaulting to `sandbox`). Namespacing/promotion logic exists. |
| **5. Candidate Promotion Logic** | Partially implemented | Manual conversion tool exists (`convert_promoted_directives.py`), but automated metric-based filtering is missing. |
| **6. State Root Configuration** | Missing | All paths are relative to `PROJECT_ROOT` or `data_root`; no centralized `STATE_ROOT` identifier found. |
| **7. Directive Replay Utility** | Already implemented | Sequential batch execution available via `python tools/run_pipeline.py --all`. |

---

## Detailed Findings

### 1. Run Container Contract
The orchestrator (`run_pipeline.py`) enforces a standard v2 structure:
```
runs/<run_id>/
  data/
  manifest.json
  run_state.json
```
Completed runs (e.g., `4c4750b00b01`) fully adhere to this structure. Startup guardrails in the orchestrator quarantine any runs failing this schema.

### 2. Directive Hashing
While `get_canonical_hash` is present in `pipeline_utils.py`, the `run_registry.json` currently uses the `directive_id` in the `directive_hash` field (e.g., `06_PA_XAUUSD...`). To reach "Already Implemented," the actual hex hash should be stored to ensure tamper-evidence.

### 3. Pipeline Version Tracking
The system passes `engine_version` through the preflight gate, but it is not saved in `run_state.json` or `run_registry.json`. This makes it difficult to audit which pipeline version produced a specific result without checking external logs or engine code.

### 4. Sandbox / Candidate Lifecycle
The `run_registry.json` includes a `tier` field, currently populated with `sandbox`. The infrastructure for multiple tiers is present, but explicitly defined candidate or production tiers were not observed in the current registry state.

### 5. Candidate Promotion Logic
`tools/convert_promoted_directives.py` provides semantic namespacing and "promotion" of legacy directives. This is a manual process. Automation that automatically flags sandbox strategies for promotion based on performance metrics (Sharpe, Drawdown, etc.) is currently missing.

### 6. State Root Configuration
Research and data paths are derived from `PROJECT_ROOT`. There is no environment variable or config field (e.g., `STATE_ROOT`) that allows redirected storage of the entire research state independently of the codebase location.

### 7. Directive Replay Utility
The orchestrator natively supports batch execution through the `--all` flag. This tool allows for the sequential re-execution of all active directives, satisfying the replay requirement.
