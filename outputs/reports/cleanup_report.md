# Standard Cleanup Run (v2.1) Report

## Executive Summary

**Strategy Layer**: **CLEAN** (Verified Idempotent)
**Portfolio Layer**: **ADVISORY ACTION REQUIRED**

The cleanup reconciler has successfully removed untracked artifacts from the Strategy Layer (`runs/` and `backtests/`). Idempotence verification confirms no further actions are pending for the Strategy Layer.

However, the Portfolio Layer reconciliation identified **3 discrepancies** that require manual attention.

---

## 1. Strategy Layer Execution

- **Status**: **SUCCESS**
- **Actions Taken**:
  - Deleted untracked run snapshots (`runs/`).
  - Deleted untracked backtest state folders (`backtests/`).
- **Verification**: Re-run of reconciler produced **zero** strategy layer actions.

## 2. Portfolio Layer Discrepancies (Advisory)

The following portfolio folders exist on disk but are **NOT** present in `strategies/Master_Portfolio_Sheet.xlsx`.

| Discrepancy Type | Target | Action Required |
| :--- | :--- | :--- |
| **ZOMBIE PORTFOLIO** | `strategies/IDX27/` | **Manual Review** |
| **ZOMBIE PORTFOLIO** | `strategies/Range_Breakout/` | **Manual Review** |
| **ZOMBIE PORTFOLIO** | `strategies/Range_Breakout03/` | **Manual Review** |

**Recommendation per SOP_CLEANUP**:

1. Check if these portfolios are still needed.
2. If **YES**: Add them to `Master_Portfolio_Sheet.xlsx`.
3. If **NO**: Manually delete the folders (or move to archive).

## 3. Compliance Statement

This cleanup run adhered to the following rules:

- **Strategy Layer**: Deletions strictly followed `Strategy_Master_Filter.xlsx` exclusion logic.
- **Portfolio Layer**: No folders were automatically deleted.
- **Independence**: Strategy and Portfolio layers were treated independently.

---
**Run Completed**: 2026-02-17
**Tool Version**: cleanup_reconciler.py (v2.1)
