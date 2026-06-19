---
name: pipeline-state-cleanup
description: Lineage-aware cleanup of TradeScan_State pipeline artifacts (runs/, backtests/, sandbox/, strategies/) — prunes only entries absent from the authoritative ledgers (Master_Portfolio_Sheet, Filtered_Strategies_Passed, portfolio.yaml). Distinct from repo-cleanup-refactor (repo + code DRY) and system-health-maintenance (system audit). Drift-triggered, not calendar.
---

This workflow executes the structured Lineage-Aware State Lifecycle sequence to safely identify, map, and prune abandoned pipelines, backtests, and artifacts while maintaining absolute referential integrity.

**Critical Authority Note:** Absolute deletion and preservation authority originates SOLELY from three top-down sources: `Master_Portfolio_Sheet.xlsx`, `Filtered_Strategies_Passed.xlsx`, and `portfolio.yaml` execution shield.
If a run or portfolio identifier is documented in these active spreadsheets or shielded by the execution config, all its corresponding staging footprint directories across `TradeScan_State/runs`, `TradeScan_State/backtests`, `TradeScan_State/sandbox`, `TradeScan_State/strategies`, and `Trade_Scan/strategies` are natively shielded.
Anything absent from these central lists is mathematically defined as "abandoned" and will be formally pruned by Phase 4.

**Manual ledger-retirement safety (2026-05-29):** when the Phase-1/2 tools cannot durably retire a stale ledger row — e.g. `portfolio_sheet` has no `is_current`/`quarantine_status` column, so a Portfolios/SAC row can only be removed by a DB delete, and `repair_integrity`'s Portfolios/SAC arm is Excel-only (wiped on next export) — and you fall back to a direct `ledger.db` edit: (1) back up `ledger.db` first (timestamped `bak_*`); (2) scope the `is_current=0`/DELETE by the EXACT target `run_id`s or the missing-disk criterion, NEVER a strategy-name `LIKE` (a broad LIKE over-touched 9 `master_filter` rows when only 5 were orphans) — and note that even a directive-id `LIKE` over-matches because SQL treats `_` as a single-character wildcard: `directive_id LIKE '%GP_ZCRS_Z25_%'` matched 986 rows, not 476 (2026-06-15). Always enumerate exact `run_id`s/`directive_id`s in an `IN (...)` list, or escape underscores with `LIKE ... ESCAPE`; never trust a bare name `LIKE` even when it looks specific; (3) use an idempotent `AND is_current=1` guard; (4) re-export MPS so the change reaches the pruner's keep-set.

**Discarding a validation / throwaway pipeline run — use `reset_directive.py`, never a bare `rm` (2026-06-19).** A directive taken to PORTFOLIO_COMPLETE *purely to exercise the pipeline* (engine-promotion / flip validation, smoke runs) leaves protected FSM state behind — `directive_state.json` `protected:true` + latest status `PORTFOLIO_COMPLETE` — **plus** ledger rows. Removing only the run's heavy artifacts (a bare `rm` of `runs/<run_id>/`, or an external prune) leaves that protected state dangling → a silent referential breach that **blocks `lineage_pruner` Phase-1B** and lurks until the pruner is next run by hand (2026-06-19: two `27_MR_XAUUSD_30M_PINBAR_S01_V1_P06` [+ `__E001`] engine-promotion test runs did exactly this — PORTFOLIO_COMPLETE + ledger metrics persisted, run_id artifacts gone). To discard such a run: `python tools/reset_directive.py <directive_id> --reason "<test residue ...>"` — it transitions PORTFOLIO_COMPLETE → FAILED → INITIALIZED, archives + clears the run folder atomically, and is audit-logged; then drop any orphan ledger rows per the *Manual ledger-retirement safety* note above. **Enforcement (not a decay-prone doc):** `system_preflight`'s `REF_INTEGRITY` check (commit `2b763168`) now flags any protected/PORTFOLIO_COMPLETE run_id whose artifacts are absent from `runs/`+`sandbox/`, so a skipped cleanup surfaces as YELLOW at the next session-start instead of lurking.

**Cointegration-corpus keep-set propagation (2026-06-16 — AUTHORITATIVE).** Operator-directed retirement of a cointegration cohort that propagates ONE keep-set decision deterministically across all four surfaces — ledger, Excel, artifacts, directives — with no per-`directive_id` hand-work. The keep-set IS the `is_current=1` set; everything else retires.

> **RETIRED — do NOT use:** the former step *"delete/quarantine the backtest dirs scoped by EXACT `directive_id` (NOT `lineage_pruner`)"*. As of commit `4da44451`, `lineage_pruner` runs on a stood-down fleet via `--allow-empty-shield`, so artifact + directive pruning is keep-set-driven, never manual-by-`directive_id`.

Sanctioned sequence (verify each step's counts before the next):
1. **Declare** the keep-set in the ledger. Back up `ledger.db` first (timestamped `bak_<ts>`), then flip `is_current` scoped by EXACT `run_id`s in an `IN (...)` list — NEVER a bare name/`directive_id` `LIKE` (`_` is a SQL single-char wildcard; `GP_ZCRS_Z25_` matched 986 vs 476, 2026-06-15), always `AND is_current=1`:
   `UPDATE cointegration_sheet SET is_current=0 WHERE run_id IN (<non-keep ids>) AND is_current=1`
2. **Excel view:** `python tools/ledger_db.py --export-mps` then `python tools/format_excel_artifact.py --profile portfolio` (`--export-mps` regenerates tabs wholesale — Phase 4 caution).
3. **Clear the integrity gate** (one-time, only if `lineage_pruner` Phase-1B reports orphan keep-rows): `python tools/state_lifecycle/repair_integrity.py` (dry-run) → `--execute` (drops authorized orphans whose disk is already gone — operator `rm` is the signal, invariant #2).
4. **Artifacts + directives:** `python tools/state_lifecycle/lineage_pruner.py --allow-empty-shield` (DRY-RUN — confirm `KEEP_RUNS`, the quarantine counts, and `[PASS] No KEEP_RUNS ID appears in delete list`) → `python tools/state_lifecycle/lineage_pruner.py --execute --allow-empty-shield` (quarantines non-keep runs + directives to `TradeScan_State/quarantine/`; reversible). NOTE: quarantined directives can include git-tracked `backtest_directives/archive/` entries — moving them is a repo change.
5. **(OPTIONAL) ledger compaction** — only to physically remove `is_current=0` rows from the live table (they are otherwise retained in-place as the SQL archive): back up `ledger.db` → dump the rows to `TradeScan_State/_retired_cointegration/retired_rows_<ts>.parquet` + a `RETIRE_MANIFEST_<ts>.json` → `DELETE FROM cointegration_sheet WHERE is_current=0` → re-run step 2. Append-only preserved by the backup + parquet archive.

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

**Note — Empty-portfolio block (RESOLVED 2026-06-16, commit `4da44451`):** when execution is stood down, `portfolio.yaml` has zero strategies. Previously `lineage_pruner.py` hard-exited (`[BLOCK] portfolio.yaml parsed but no strategies found`, `lineage_pruner.py:164`). It now accepts **`--allow-empty-shield`**, which treats an empty-but-valid `portfolio.yaml` as an empty execution shield (nothing deployed → nothing to shield) and proceeds keep-set-driven — the keep-set is ledger-sourced (FSP/MPS/`cointegration_sheet is_current=1`/PORTFOLIO_COMPLETE), independent of `portfolio.yaml`. A MISSING/malformed `portfolio.yaml` still blocks. So a stood-down-fleet prune appends `--allow-empty-shield` to the Phase 2/3 commands below (and uses the keep-set propagation sequence above), NOT a manual `directive_id` delete.

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

**Caution:** MPS/FSP are a VIEWING LAYER ONLY (AGENT.md #32, see [`/format-excel-ledgers`](../format-excel-ledgers/SKILL.md)). `--export-mps` regenerates tabs wholesale and wipes any hand-added xlsx column; displayed columns live in `tools/portfolio/*_view.py`. (Same caution applies to the corpus-purge step that calls `--export-mps`.)

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
| 2026-05-22 | Phase 1 referenced removed `tmp/hydrate_sandbox.py`; one-time bootstrap | Removed Phase 1 entirely; renumbered Phases 2–5 → 1–4 |
| 2026-05-29 | Manual ledger flip via name LIKE over-touched 9 rows (5 orphans); needed restore | Added ledger-retirement safety note: scope by exact run_id; back up + AND-guard |
| 2026-06-15 | id LIKE over-matched (SQL `_`=wildcard, 986 vs 476); empty-portfolio block | Added corpus-purge + empty-portfolio-block + LIKE-escape (`_`/IN) notes |
| 2026-06-16 | Empty-portfolio block forced manual per-directive_id deletes, stood-down fleet | `--allow-empty-shield` (4da44451); keep-set-driven prune; manual step retired |
| 2026-06-19 | Phase-1B blocked by protected PORTFOLIO_COMPLETE runs whose artifacts were gone (engine-promotion test residue); silent until run by hand | Added "discard via reset_directive, not bare rm" contract + `system_preflight` REF_INTEGRITY tripwire (`2b763168`) |
