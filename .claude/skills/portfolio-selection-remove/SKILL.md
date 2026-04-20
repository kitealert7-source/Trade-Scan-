---
name: portfolio-selection-remove
description: Remove a strategy from the active portfolio selection (clear IN_PORTFOLIO flag)
---

# Portfolio Selection — Remove Strategy

Use this workflow when a strategy must be removed from the live portfolio — e.g., replaced by a superior pass, retired due to degraded performance, or excluded after further analysis.

---

### Step 1: Identify the Run ID to Remove

The `--clear` command takes a `run_id`, not a strategy name.

Find the run ID:
```bash
python tools/sync_portfolio_flags.py --list
```

This lists all currently persisted `IN_PORTFOLIO = True` run_ids. Identify the one to remove.

If you need to match a strategy name to a run_id, check:
- `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx` — `run_id` column
- `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx` — `run_id` column

### Step 2: Clear the Selection

// turbo

```bash
python tools/sync_portfolio_flags.py --clear <RUN_ID>
```

Replace `<RUN_ID>` with the actual run ID (e.g., `23_RSI_XAUUSD_1H_MICROREV_S01_V1_P11_XAUUSD`).

This command:
1. Removes the `run_id` from `TradeScan_State/sandbox/in_portfolio_selections.json`
2. Sets `IN_PORTFOLIO = False` in `Strategy_Master_Filter.xlsx` for that run_id
3. Does NOT modify `Filtered_Strategies_Passed.xlsx` (candidates sheet is operator-managed)

Expected output:
```
[CLEAR] Removed '<RUN_ID>' from selections store (N remaining).
[CLEAR] IN_PORTFOLIO set to False in Master Filter for '<RUN_ID>'.
```

> [!NOTE]
> If the run_id is not found in the store, no action is taken. If not found in the Master Filter (but in the store), the store is still cleared.

### Step 3: Manually Clear in Filtered_Strategies_Passed.xlsx (Optional)

The `--clear` command does not touch `Filtered_Strategies_Passed.xlsx`. If you want the candidates sheet to reflect the removal:

1. Open `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx`
2. Find the row for the removed strategy
3. Set `IN_PORTFOLIO = False` (or leave blank)

> Do NOT run `--save` after this step unless you want all remaining True flags to be re-merged. If you do run `--save`, the cleared run_id (already removed from the store) will not be re-added.

### Step 4: Verify Removal

```bash
python tools/sync_portfolio_flags.py --list
```

Confirm the run_id is no longer in the list.

### Step 5: Update Project Memory

Update `project_portfolio_composition.md` to reflect the removed strategy. If a replacement was added, update that entry too.

---

## Swap Procedure (Remove + Add)

When swapping a strategy (e.g., P11 → P12):

```bash
# 1. Remove old pass
python tools/sync_portfolio_flags.py --clear <OLD_RUN_ID>

# 2. Mark new pass True in Filtered_Strategies_Passed.xlsx (manually in Excel)

# 3. Persist new selection
python tools/sync_portfolio_flags.py --save

# 4. Verify
python tools/sync_portfolio_flags.py --list
```

---

## System Contract

- `--clear` is the ONLY operator-sanctioned way to flip `IN_PORTFOLIO True → False`.
- No pipeline code path (including `stage3_compiler`) may remove a True flag once set.
- After a Master Filter rebuild, run `--apply` to restore all persisted True flags.
