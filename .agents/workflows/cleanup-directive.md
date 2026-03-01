---
description: Standard cleanup run — reconcile filesystem artifacts against authoritative ledgers
---

# Standard Cleanup Run (v2.1)

Two authoritative ledgers exist:

1. **Strategy Layer:** `backtests/Strategy_Master_Filter.xlsx` — governs strategy run retention.
2. **Portfolio Layer:** `strategies/Master_Portfolio_Sheet.xlsx` — governs portfolio folder existence.

The filesystem must be reconciled against both ledgers independently.

---

## Step 1 — Strategy Layer Dry-Run

Run the cleanup reconciler in **dry-run mode** (no deletions):

// turbo

```
python tools/cleanup_reconciler.py
```

**Validate** before proceeding:

- Every planned deletion targets artifacts **not** represented in `Strategy_Master_Filter.xlsx`.
- No artifact still represented in `Strategy_Master_Filter.xlsx` is scheduled for deletion.
- Action ordering is deterministic.

If the dry-run output shows unexpected deletions, **STOP** and report the discrepancy. Do NOT proceed to Step 2.

---

## Step 2 — Strategy Layer Execute

If and only if the dry-run output from Step 1 is correct, run cleanup in **execute mode**:

```
python tools/cleanup_reconciler.py --execute
```

---

## Step 3 — Post-Execution Verification

After execution, verify:

- All planned deletions were applied.
- Preserved artifacts remain untouched.

Re-run the reconciler to confirm **idempotence** (expect zero actions):

// turbo

```
python tools/cleanup_reconciler.py
```

If any actions remain, report the residual items as a failure.

---

## Step 4 — Portfolio Layer Reconciliation (Advisory Only)

Independently reconcile portfolio folders. Compare:

- `strategies/<portfolio_id>/` folders on disk

Against:

- `strategies/Master_Portfolio_Sheet.xlsx` entries

**Validate:**

- Any portfolio folder **without** a corresponding `Master_Portfolio_Sheet.xlsx` entry is flagged.
- Any `Master_Portfolio_Sheet.xlsx` row **without** a corresponding folder is flagged.

> [!CAUTION]
> No portfolio folder deletion is performed automatically. Portfolio cleanup is **advisory only**.
> If mismatch exists, report the discrepancy. Do NOT auto-delete portfolio folders.
> Manual action is required per `SOP_CLEANUP.md`.

---

## Step 5 — Final Report

Report **PASS** if:

- Strategy layer cleanup converges to no actions (idempotent).
- No unexpected portfolio discrepancies exist.

Report **FAIL** with the first unexpected action only.

---

## Rules

- Do not infer intent beyond authoritative ledgers.
- Do not manually delete files.
- Do not add heuristics or extra cleanup.
- Treat file locks or transient failures as non-fatal; allow next run to converge.
- Strategy and Portfolio layers must remain strictly independent.
- Do NOT touch `runs/*/run_state.json` — run state cleanup is exclusively handled by `tools/reset_directive.py`.
- Do NOT touch `tools/*.json` (manifests), `vault/` (root-of-trust), or `governance/` (audit logs).
- Do NOT delete `strategies/<NAME>/deployable/` folders — these are capital wrapper outputs and may be independently consumed.
