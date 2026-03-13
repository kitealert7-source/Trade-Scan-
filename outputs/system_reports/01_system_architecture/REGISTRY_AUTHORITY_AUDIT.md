# Registry Authority Verification Audit

This document details the read-only architectural audit of the `registry/` folder, verifying whether its contents belong to the repository (SOURCE) or to the runtime state (STATE).

---

## 1. Registry Contents

| File | Observed Location | Purpose |
| :--- | :--- | :--- |
| `run_registry.json` | `Trade_Scan/registry/` | **LEGACY**: Contains stale run history (last entry 2026-03-12). |
| `run_registry.json` | `TradeScan_State/registry/` | **ACTIVE**: Authoritative lifecycle ledger (last entry 2026-03-13). |
| `engine_registry.json` | `Trade_Scan/registry/` | **SOURCE**: Defines `active_engine` version and vault paths. |

---

## 2. Usage Trace

### `run_registry.json`
- **Primary Manager**: `tools/system_registry.py` handles atomic writes and reconciliation.
- **Orchestration**: `run_planner.py` and `stage_symbol_execution.py` reference it for run-state tracking.
- **Path Authority**: `config/state_paths.py` explicitly defines `REGISTRY_DIR` as external to the repository.

### `engine_registry.json`
- **Primary Consumer**: `config/engine_loader.py` reads this file to determine the active research engine.
- **Usage**: Mentioned in `RESRCH_INFRA_HARDENING_SUMMARY.md` as the "Central Registry" for engine versions.

---

## 3. Mutation Analysis

### `run_registry.json` (STATE)
- **High Mutation Area**: Frequently updated during pipeline execution.
- **Logic**: Contains `log_run_to_registry` and `_save_registry_atomic` functions in `system_registry.py`.
- **Classification**: This is a **mutable runtime ledger**. While it represents the "Truth," its residence must be in the **STATE** layer because it captures the history of execution artifacts.

### `engine_registry.json` (SOURCE/CONFIG)
- **Static Configuration**: No write logic detected in the codebase.
- **Function**: Acts as a versioned baseline that stays with the source code to define which infrastructure version to load.
- **Classification**: Strictly **SOURCE** (Configuration).

---

## 4. Authority Classification & Boundary Check

| Artifact | Recommended Authority | Logical Layer | Residency |
| :--- | :--- | :--- | :--- |
| `engine_registry.json` | **SOURCE** | Tools / Control | `Trade_Scan/` |
| `run_registry.json` | **STATE** | Lifecycle / State | `TradeScan_State/` |

---

## 5. Architecture Alignment

The current classification of `registry/` as `TRUST_AUTHORITY` in the `REPOSITORY_AUTHORITY_MAP.md` is **partially accurate** but physically ambiguous.

- **The Problem**: A `registry/` folder still exists inside the repository containing a legacy `run_registry.json`. This creates a shadow-ledger risk.
- **Alignment Requirement**: The system must distinguish between **Static Config Registries** (Source) and **Mutable Lifecycle Registries** (State).

---

## 6. Safe Recommendations

| Item | Current Location | Observed Behavior | Recommended Classification | Suggested Action |
| :--- | :--- | :--- | :--- | :--- |
| **Internal Run Ledger** | `Trade_Scan/registry/run_registry.json` | Dead/Stale history | **LEGACY** | Delete internal copy. |
| **Active Run Ledger** | `TradeScan_State/registry/run_registry.json` | Active mutations | **STATE** | Maintain in external root. |
| **Engine Baseline** | `Trade_Scan/registry/engine_registry.json` | Static config | **SOURCE** | Retain in repository. |

---

## 7. Risk Assessment

1. **Risk of Breaking Execution**: LOW. The code in `state_paths.py` already ignores the internal registry.
2. **Dependency Impact**: NO IMPACT. Orchestration modules use central pathing logic.
3. **Migration Strategy**: Mechanical cleanup. The internal `run_registry.json` is a duplicate that can be safely pruned.

---

## 8. Stability Rule

**Authority Separation Rule**:
> No file inside the `Trade_Scan` repository should be opened for **WRITE** access during a standard pipeline execution (Stage 1-6).
> 
> Mutable ledgers (like `run_registry.json`) belong exclusively to the external `TradeScan_State/` environment to preserve the "Clean Repository" architecture.

---
**Status**: Registry Audit Complete | **Version**: 1.0.0
