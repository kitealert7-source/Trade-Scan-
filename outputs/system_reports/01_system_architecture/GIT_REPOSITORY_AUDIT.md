# Git Repository State Audit

This document provides a read-only audit of the `Trade_Scan` Git repository configuration, tracking status, and architectural boundary compliance.

---

## 1. Repository Status Summary
- **Active Branch**: `main`
- **Staged Changes**: Extensive deletions in `BACKUPDATA/`, `outputs/system_reports/`, and the legacy `registry/run_registry.json`.
- **Modified Files**: Core logic in `tools/`, `governance/`, and `engine_dev/` awaiting commit.
- **Untracked Files**:
    - `config/` (contains critical `engine_registry.json`).
    - New `outputs/system_reports/` architectural docs.
    - Local `backtest_directives/active/*.txt`.

---

## 2. Tracked Files Overview
The repository currently tracks **~3000 files**. Analysis reveals significant "leakage" of non-source artifacts into the Git index.

### Authority Violations:
| Path | Category | Violation Type | Description |
| :--- | :--- | :--- | :--- |
| `archive/legacy_runs/` | **STATE** | Mutable leakage | Tracked JSON run states, strategy scripts, and audit logs. |
| `data_root/` | **DATA_AUTHORITY** | Hybrid leakage | Tracked docs and runtime state (`last_successful_daily_run.json`). |
| `vault/` | **TRUST_AUTHORITY** | Valid tracking | Explicitly tracked via `!vault/` rule. |

---

## 3. Ignored Paths Analysis
The current `.gitignore` covers basic Python and runtime artifacts but lacks coverage for newer architectural components.

### Missing Ignore Rules:
- `TradeScan_State/` (Sibling root protection)
- `sandbox/` (Temporary execution root)
- `reports_summary/` (Aggregated state)
- `**/backtest_directives/active/*.txt` (User-specific directives)
- `.claude/`, `.agents/`, `.skills/` (Environment-specific IDE metadata)

---

## 4. Large / Generated Artifact Scan
- **Spreadsheets**: No `.xlsx` files detected in the current index (Successfully ignored).
- **CSV Data**: `*.csv` is globally ignored.
- **Binary Data**: No `.parquet` or `.zip` files detected in the index.

---

## 5. Architecture Boundary Check
The repository violates the **Clean Repository** principle in several areas:

1.  **Registry Drift**: `registry/engine_registry.json` is tracked, but `config/engine_loader.py` expects the registry at `config/engine_registry.json` (which is untracked).
2.  **Legacy Bloat**: Hundreds of individual run artifacts are tracked in `archive/legacy_runs/`. These should be moved to an external state archive.
3.  **Data Root Leakage**: Metadata and governance documents are committed inside `data_root/`, making the folder a mix of code and mutable reference data.

---

## 6. Recommended .gitignore Adjustments

```gitignore
# Sibling state root
../TradeScan_State/

# Specific missing state folders
sandbox/
reports_summary/

# Local directive safety
backtest_directives/active/*.txt
!backtest_directives/active/README.md

# Large data formats
*.parquet
*.h5
*.pickle

# Environment metadata
.claude/
.agents/
.vscode/
```

---

## 7. Recommended Git Hygiene Actions

1.  **Prune Legacy Runs**: Run `git rm -r --cached archive/legacy_runs/` and move them to external state storage.
2.  **Fix Registry Pathing**: Align the code and Git index to track **one** authoritative `engine_registry.json` (Recommended: `config/engine_registry.json`).
3.  **Clean Data Root**: Remove `data_root/` from the Git index and maintain it as a purely external/symbolic authority.

---
**Status**: Git Audit Complete | **Verdict**: HYGIENE_VIOLATION | **Version**: 1.0.0
