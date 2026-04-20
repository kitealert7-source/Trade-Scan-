---
description: Add one or more strategies to the active portfolio selection (IN_PORTFOLIO flag)
---

# Portfolio Selection — Add Strategy

Use this workflow when the user decides to include a strategy in the live portfolio after evaluation.

---

### Step 0: Lifecycle Guard (MANDATORY)

Before adding ANY strategy to portfolio.yaml, verify it was promoted through the `/promote` workflow:

```bash
python tools/lifecycle_status.py
```

**Hard check:** If the strategy does not appear in `lifecycle_status.py` output with state `BURN_IN`, `WAITING`, or `LIVE`, it has NOT been promoted.

> **FAIL condition:** Do NOT add a strategy to portfolio.yaml manually. The `/promote` workflow (`tools/promote_to_burnin.py`) is the ONLY path that creates vault snapshots and writes `vault_id`, `profile`, and `lifecycle` fields. Entries without these fields are untracked and break lifecycle invariants.
>
> If the strategy needs to enter portfolio.yaml → run `/promote` first.

---

### Step 1: Identify the Run ID

The run ID is the key that links `Filtered_Strategies_Passed.xlsx` ↔ `Strategy_Master_Filter.xlsx` ↔ `in_portfolio_selections.json`.

Find it from one of these sources:
- The `run_id` column in `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx`
- The pipeline output line: `[Stage-3] Promoted to candidates: <RUN_ID>`
- `TradeScan_State/runs/<DIRECTIVE_ID>/run_registry.json`

### Step 2: Mark IN_PORTFOLIO in Filtered_Strategies_Passed.xlsx

Open `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx` and set `IN_PORTFOLIO = True` for the target row(s).

> [!IMPORTANT]
> The source of truth for selection is `Filtered_Strategies_Passed.xlsx` (candidates sheet).
> The `--save` command reads True flags from THIS sheet, not from the Master Filter.

### Step 3: Persist the Selection

// turbo

```bash
python tools/sync_portfolio_flags.py --save
```

This command:
1. Reads all `IN_PORTFOLIO = True` rows from `Filtered_Strategies_Passed.xlsx`
2. Merges their `run_id`s into `TradeScan_State/sandbox/in_portfolio_selections.json` (append-only store)
3. Mirrors the True flags back into `Strategy_Master_Filter.xlsx` so both sheets are in sync
4. Reports new additions with strategy names

Expected output:
```
[SAVE] N True flag(s) in Filtered_Strategies_Passed.
[SAVE] 1 new run_id(s) added to store:
  + 23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12
[SAVE] Store now contains N persisted selection(s).
[SAVE] Mirrored N True flag(s) to Strategy_Master_Filter (1 new).
```

### Step 4: Verify Selection is Persisted

```bash
python tools/sync_portfolio_flags.py --list
```

Confirm the new run_id appears in the list.

### Step 5: Update Project Memory

Save the portfolio composition change to memory (`project_portfolio_composition.md`) so future conversations have an accurate picture of the live portfolio.

---

## Persistence Guarantee

The `in_portfolio_selections.json` store is sticky by design. Even after a full `stage3_compiler` rebuild (which regenerates `Strategy_Master_Filter.xlsx`), the `--apply` command restores all persisted True flags:

```bash
python tools/sync_portfolio_flags.py --apply
```

Run `--apply` any time the Master Filter is rebuilt from scratch to restore all selections.

---

## System Contract

- `IN_PORTFOLIO` flags flow: `Filtered_Strategies_Passed.xlsx` → `--save` → `in_portfolio_selections.json` → `--apply` → `Strategy_Master_Filter.xlsx`
- No pipeline code path may flip `IN_PORTFOLIO True → False`. Only `--clear` does.
- `in_portfolio_selections.json` is append-only via `--save`. Only `--clear` removes entries.
