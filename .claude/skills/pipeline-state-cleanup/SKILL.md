---
name: pipeline-state-cleanup
description: Lineage-aware cleanup of TradeScan_State pipeline artifacts (runs/, backtests/, sandbox/, strategies/) — prunes only entries absent from the authoritative ledgers (Master_Portfolio_Sheet, Filtered_Strategies_Passed, portfolio.yaml). Distinct from repo-cleanup-refactor (repo + code DRY) and system-health-maintenance (system audit). Drift-triggered, not calendar.
---

This workflow executes the structured Lineage-Aware State Lifecycle sequence to safely identify, map, and prune abandoned pipelines, backtests, and artifacts while maintaining absolute referential integrity.

**Critical Authority Note:** Absolute deletion and preservation authority originates SOLELY from three top-down sources: `Master_Portfolio_Sheet.xlsx`, `Filtered_Strategies_Passed.xlsx`, and `portfolio.yaml` execution shield.
If a run or portfolio identifier is documented in these active spreadsheets or shielded by the execution config, all its corresponding staging footprint directories across `TradeScan_State/runs`, `TradeScan_State/backtests`, `TradeScan_State/sandbox`, `TradeScan_State/strategies`, and `Trade_Scan/strategies` are natively shielded.
Anything absent from these central lists is mathematically defined as "abandoned" and will be formally pruned by Phase 4.

**Manual ledger-retirement safety (2026-05-29):** when the Phase-1/2 tools cannot durably retire a stale ledger row — e.g. `portfolio_sheet` has no `is_current`/`quarantine_status` column, so a Portfolios/SAC row can only be removed by a DB delete, and `repair_integrity`'s Portfolios/SAC arm is Excel-only (wiped on next export) — and you fall back to a direct `ledger.db` edit: (1) back up `ledger.db` first (timestamped `bak_*`); (2) scope the `is_current=0`/DELETE by the EXACT target `run_id`s or the missing-disk criterion, NEVER a strategy-name `LIKE` (a broad LIKE over-touched 9 `master_filter` rows when only 5 were orphans); (3) use an idempotent `AND is_current=1` guard; (4) re-export MPS so the change reaches the pruner's keep-set.

### Phase 1: Diagnose & Repair Structural Decay

(Optional) Automatically locate missing strings from active tracking spreadsheets `Master_Portfolio_Sheet.xlsx` and `Filtered_Strategies_Passed.xlsx` against physical files on disk, actively dropping rows/portfolios that contain no live counterparts. This neutralizes structural database decay.

```powershell
python tools/state_lifecycle/repair_integrity.py
```

### Phase 2: Validate Quarantine Sequence (Dry Run)

Evaluate the physical tracking geometries strictly across Master and Filtered lists without running mutations. Will abort immediately if invariants fail (e.g. if a mapped run ID lacks a physical directory). Outputs grouped counts natively.

```powershell
python tools/state_lifecycle/lineage_pruner.py
```

### Phase 3: Execute Formal Lineage Cleanup

Physically sequence all unmapped abandoned elements structurally out of active processing areas (`runs/`, `backtests/`, `directives/`, `strategies/`) directly into an isolated snapshot directory natively under `TradeScan_State/quarantine/`.

```powershell
python tools/state_lifecycle/lineage_pruner.py --execute
```

**Note:** If Phase 2/3 is blocked by a stale TS_Execution PID, verify the process is dead and re-run with `--force-unlock`:
```powershell
python tools/state_lifecycle/lineage_pruner.py --force-unlock
python tools/state_lifecycle/lineage_pruner.py --force-unlock --execute
```

### Phase 4: Aesthetic Validation & Formatting

Finally, execute the native formatting engines over the surviving matrices to physically ensure visual constraints (Data Bars, Ranking, Status Highlighting) are perfectly maintained.

// turbo
```powershell
python tools/format_excel_artifact.py --file "C:\Users\faraw\Documents\TradeScan_State\candidates\Filtered_Strategies_Passed.xlsx" --profile strategy
python tools/format_excel_artifact.py --file "C:\Users\faraw\Documents\TradeScan_State\strategies\Master_Portfolio_Sheet.xlsx" --profile portfolio
```

---

## Retire superseded runs (post-rerun, batch) — cold-archive + prune

Invoked by [`/rerun-backtest`](../rerun-backtest/SKILL.md) **Phase C**, per batch, after a rerun
batch's new runs land. Unlike Phases 1–4 (which prune what is **absent** from the ledgers), retire
targets runs that are **present but superseded** (`is_current=0`, with a live successor) — trimming
the predecessor once its rerun has consumed its seed (directive + `RECYCLE_RULE_SOURCE.py`).

Per batch, scoped to the EXACT predecessor `run_id`s:

1. **Archive → cold parquet.** Append each superseded run's compact row to
   `TradeScan_State/retired/retired_runs.parquet` (schema below). Append-only; this is the
   queryable retired-results / **don't-re-test** base (feeds the F19 guard without artifacts).
2. **Drop the live row** via the authorized path (`repair_integrity.py --action drop`), scoped by
   **exact `run_id`s + an `AND is_current=0` guard — never a name `LIKE`** (cf. the *Manual
   ledger-retirement safety* note above; back up `ledger.db` first). **Archive-BEFORE-drop** makes
   it a *move*, not a destroy — the ONLY sanctioned ledger-row removal (Invariant #2). For baskets,
   the target sheet is `cointegration_sheet` / `basket_sheet` (not `master_filter`).
3. **Prune heavy artifacts** (`runs/<run_id>/`, `backtests/<name>/`) via the lineage pruner
   (→ `quarantine/`, then deletable in bulk). The cold row keeps the numbers.

**Cold-archive schema (`retired_runs.parquet`):** `run_id, directive_id, source_sheet
(master_filter | cointegration_sheet | basket_sheet), engine_version, pair_or_symbol, test_start,
test_end, net_pct, ret_dd, max_dd_pct, trades, cycles, supersede_reason, superseded_by,
retired_at_utc`.

> **Tool support pending:** a `--retire-batch <run_ids>` mode wrapping steps 1–3 atomically, plus a
> **drift check** (count `is_current=0` runs with on-disk artifacts not in `retired_runs.parquet`,
> surfaced in `/session-close`), are pending. Until built, run steps 1–3 by hand per batch with the
> exact-`run_id` scoping + backup discipline above.

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| 2026-05-22 | Phase 1 referenced `tmp/hydrate_sandbox.py` which no longer exists; was a one-time pipeline-restructure bootstrap, not recurring infrastructure | Removed Phase 1 entirely; renumbered Phases 2–5 → 1–4 |
| 2026-05-29 | Manual ledger flip used a strategy-name LIKE → over-touched 9 rows (5 were orphans); needed backup recovery | Added "Manual ledger-retirement safety" note: scope by exact run_ids/missing-disk; back up + AND-guard |
