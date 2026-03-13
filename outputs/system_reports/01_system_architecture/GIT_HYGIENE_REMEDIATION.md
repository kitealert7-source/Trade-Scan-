# Git Hygiene Remediation Report

This report summarizes the remediation actions taken to align the `Trade_Scan` repository's Git index with architectural boundaries.

---

## 1. Removed From Git Index (Non-destructive)
The following directories have been untracked from Git using `git rm --cached`. Local physical files remain untouched on disk.

- `archive/legacy_runs/`
- `data_root/`

These folders are now untracked and should remain outside of version control as they contain either legacy state or external data authority items.

---

## 2. Updated .gitignore Rules
The `.gitignore` file was updated to include the following architectural protect rules:

```gitignore
# External runtime state
../TradeScan_State/

# Runtime folders
sandbox/
reports_summary/

# Local directive safety
backtest_directives/active/*.txt
!backtest_directives/active/README.md

# Data artifacts
*.parquet
*.h5
*.pickle

# Environment metadata
.claude/
.agents/
.vscode/
```

---

## 3. Remaining Tracked Directories
- `vault/` (Explicitly tracked as **TRUST_AUTHORITY**).
- `engines/` & `engine_dev/` (**ENGINE**).
- `tools/` (**SOURCE**).
- `outputs/system_reports/` (**SOURCE** / Documentation).

---

## 4. Registry Alignment Status (Resolved)
- **Internal Registry**: `registry/engine_registry.json` has been **UNTRACKED** from the Git index.
- **Active Registry**: `config/engine_registry.json` is now **TRACKED** and staged as the authoritative pointer.

---

## 5. Engine Registry Resolution
- **Detection**: Found structural difference between legacy metadata registry (`registry/`) and active runner pointer (`config/`).
- **Confirmation**: Verified that `config/engine_loader.py` exclusively uses the `config/` location.
- **Action**: Performed a safe Git index swap using `git rm --cached` and `git add`.
- **Verification**: `git ls-files` confirms only the operational configuration is tracked.

---

## 6. Completion Signal

**ENGINE_REGISTRY_ALIGNMENT_READY**

All hygiene and alignment changes are staged in the Git index. No commit has been created.

---
**Status**: Remediation Complete | **Index State**: Staged | **Version**: 1.1.0
