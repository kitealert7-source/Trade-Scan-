# Cointegration Refresh — Minimum-Fix Implementation Plan (Option B)

**Date:** 2026-06-07
**Status:** Read-only plan for review. **No code until approved.**
**Scope (operator-locked):** Minimum cointegration-only fix. Reuse existing architecture. **No** governance exceptions, **no** delete/replace, **no** platform-wide redesign, **no** identity-preserving ledger migration. `master_filter`, `mark_superseded`, quarantine, portfolio logic, AGENT.md invariants, and the platform rerun architecture are **untouched.**
**Why no governance change:** `cointegration_sheet` is **not** an AGENT.md ledger — invariant #1 names only `Master_Portfolio_Sheet.xlsx` + `Strategy_Master_Filter.xlsx` (`AGENT.md:39`). Its "append-only" is a writer guard, not a charter rule. This fix preserves append-only behavior anyway (flip, never delete).

---

## 1. Verified code paths (the two pivots + supporting facts)

| Fact | Location | Note |
|---|---|---|
| **Uniqueness guard (def)** | `run_pipeline.py:505-519` `verify_directive_uniqueness_guard` | scans `run_registry` for any entry with `directive_id == this` → raises "already executed" |
| **Uniqueness guard (call site)** | `run_pipeline.py:1620` (top of `run_single_directive`, **before** `_try_basket_dispatch` at `:1624`) | single insertion point for refresh-awareness |
| **Cointegration write gate** | `run_pipeline.py:1065` `if _basket_block.get("cointegration_join")` | the natural cointegration-only scope boundary |
| **Row build (has directive_id + run_id)** | `run_pipeline.py:1086-1095` `build_cointegration_row(... directive_id=directive_id, run_id=run_id ...)` | both identities in hand at the write site |
| **Append call** | `run_pipeline.py:1096` `append_cointegration_row(_coint_row)` | |
| **Writer** | `cointegration_ledger_writer.py:88-127` | appends `is_current=1`; FATAL only on **duplicate run_id** (`:115`) → a new-run_id refresh appends cleanly |
| **Dormant supersession columns** | `cointegration_schema.py` (COINTEGRATION_SHEET_COLUMNS) | `is_current`, `superseded_by`, `superseded_at`, `supersede_reason`, `supersede_kind` — present, never written |
| **`mark_superseded`** | `ledger_db.py:791-859` | **master_filter-ONLY** (UPDATEs `master_filter` at `:836,845`) — NOT reused; a cointegration sibling is added |

---

## 2. The three changes (affected files + exact insertion points)

### CHANGE 1 — Refresh-aware uniqueness guard
**File:** `tools/run_pipeline.py` (`:505-519`, `:1616-1620`).
- Thread a `refresh: bool = False` parameter: CLI/entrypoint → `run_single_directive(directive_id, refresh=…)` → `verify_directive_uniqueness_guard(directive_id, refresh=…)`.
- When `refresh=True`, the guard **skips** the "already executed" raise (logs `[REFRESH] re-running {directive_id}`) and proceeds to `_try_basket_dispatch`.
- `refresh=False` path is byte-identical to today (zero change for normal runs).
- **Scoping:** `refresh=True` is set **only** by the cointegration refresh entrypoint (Change 3), which validates the directive is a cointegration directive — so nothing else can trigger it.

### CHANGE 2 — Writer maintains one-current-per-directive (the dormant-field flip)
**File:** `tools/portfolio/cointegration_ledger_writer.py` (`append_cointegration_row`, after the INSERT at `~:125`).
- After inserting the new row, run **one UPDATE** using the dormant columns:
  ```
  UPDATE cointegration_sheet
     SET is_current=0, superseded_by=:new_run_id, superseded_at=:utc,
         supersede_kind='re-run', supersede_reason='superseded by refresh run'
   WHERE directive_id=:directive_id AND run_id != :new_run_id AND is_current=1
  ```
- **Unconditional** (no refresh flag needed in the writer): a no-op when there is no prior row, so it only fires on a genuine re-run — and the uniqueness guard already prevents non-refresh re-runs. **Backward-compatible** (existing 1-row-per-directive corpus → no priors → no flips) and **self-healing** (collapses any existing duplicate `is_current=1` to the newest).
- **Append-only preserved** — flip, never delete. The FATAL-on-duplicate-**run_id** guard (`:115`) stays (a refresh has a new run_id, so it never fires; run_id uniqueness is intact).
- *(Alternative placement: `run_pipeline.py:1096` right after the append — `directive_id`+`run_id` are in `_coint_row`. The writer is preferred: self-contained, future-caller-safe.)*

### CHANGE 3 — First-class cointegration refresh entrypoint
**File:** new `tools/refresh_cointegration.py` (small, mirrors the `rerun_backtest.py` shape but cointegration-scoped and single-phase — no `__E###`, no `finalize`).
- CLI: `python tools/refresh_cointegration.py <directive_id> --category {ENGINE|DATA_FRESH|PARAMETER|BUG_FIX} --reason "…"`.
- Steps: (1) **validate** the directive exists and is a cointegration directive (`basket.cointegration_join` present) — refuse otherwise (scope guard); (2) **window-match** (`feedback_test_window_must_match_signal_class`): for `DATA_FRESH`, re-derive the pair's *current* cointegrated span from the screener and set `end_date` to it — never blind-extend; for `ENGINE`/provenance, reuse the recorded window unchanged; (3) inject `test.repeat_override_reason` (≥50 chars — bypasses the Idea Gate) + `test.rerun_of=<prior run_id>` breadcrumb; (4) re-stage to `backtest_directives/INBOX/`; (5) run `run_pipeline` with `refresh=True` (Change 1); (6) the run mints a **new run_id + full provenance receipt** (`runs/<run_id>/manifest.json` incl. `broker_spec_sha256`), appends the cointegration row, and the writer (Change 2) flips the prior.

> **DEBT MARKER (operator note, 2026-06-07):** the use of `repeat_override_reason` here is a **temporary reuse of the existing rerun authorization path** (the field was designed for the Idea-Gate `REPEAT_FAILED` bypass), **not** a "cointegration refresh architecture." It is acceptable *only* because the pilot is minimizing scope. Mark it as such in the entrypoint's code comment so we don't accidentally create a permanent dependency on a field built for something else; a dedicated `refresh`-intent signal is the eventual replacement. Not a blocker for the pilot.
- **Lineage** rides the existing channels — the `superseded_by` chain on the flipped row + the new run receipt + the normal run audit log. **No new audit log** (that was the platform-wide idea).

**Maps to the 5 required properties:** (1) reuse existing `directive_id` — Change 1 (no rename); (2) new run_id + provenance — the normal pipeline run; (3) append a new row — existing writer; (4) flip prior to `is_current=0` via dormant fields — Change 2; (5) everything else unchanged — see §4.

---

## 3. Migration impact: **NONE**
- **No schema change** — the five supersession columns already exist on `cointegration_sheet`.
- **No data migration** — the writer flip is a no-op on the existing 1-row-per-directive corpus; it activates only on refresh.
- **Backward-compatible + self-healing** — un-refreshed directives are untouched; any pre-existing duplicate-current rows collapse to newest on their next refresh.
- **No PK change, no delete, no `mark_superseded` change, no `master_filter` touch.**

---

## 4. Explicitly unchanged (scope fences)
- `master_filter` write/read behavior, `mark_superseded`, `rerun_backtest.py`, the `__E###` path (still used for genuine new-research variants elsewhere) — **untouched**.
- `quarantine`/`quarantine_status` semantics + its ~6 consumers — **untouched** (orthogonal disposition system).
- Portfolio logic, `portfolio.yaml`, promotion/vault/composite — **untouched**.
- AGENT.md invariants — **none modified** (cointegration_sheet isn't a named ledger; append-only behavior preserved).
- Platform-wide rerun architecture / identity-preserving ledger migration — **not pursued** (deferred direction only).

---

## 5. Validation steps (before CADJPY/USDCHF)
1. **Writer unit tests** (`test_cointegration_ledger_writer` / new): (a) first append for directive D → 1 row `is_current=1`, no flip; (b) second append for D with a new run_id → exactly one `is_current=1` (newest), prior flipped `is_current=0` + `superseded_by`/`superseded_at`/`supersede_kind='re-run'` set; (c) duplicate **run_id** still raises FATAL (run_id append-only intact); (d) two *different* directives are independent (no cross-flip).
2. **Guard unit test:** `verify_directive_uniqueness_guard(id, refresh=True)` passes for an existing id; `refresh=False` still raises.
3. **Reader regression:** `cointegration_aggregator.py:84` + `trade_candidates_view.py` over the existing corpus return identical results (no `is_current=0` introduced for un-refreshed directives; per-pair runs-count unchanged).
4. **Scoped integration:** refresh a throwaway cointegration directive end-to-end → one `is_current=1` row, prior flipped, new `runs/<run_id>/manifest.json` carries `broker_spec_sha256`, screener untouched.
5. **Pre-commit gates:** the run goes through normal admission (`window_validity_gate`, namespace, Idea-Gate-via-override) — confirm a refresh passes them.

## 6. CADJPY/USDCHF refresh → promotion unblock
- `python tools/refresh_cointegration.py 90_PORT_CADJPYUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS__E260312 --category ENGINE --reason "capture broker_spec provenance for promotion; provenance fix landed 8ee1b87e"`.
  - Re-runs the recorded window (03-12→06-04) — **ENGINE** category, window unchanged → `window_validity_gate` trivially passes. *(Or `--category DATA_FRESH` to re-derive the current 06-05 span; either is window-match-safe.)*
  - Produces a fresh run_id recording `broker_spec_sha256`; flips `74d26f18407d` → `is_current=0` (retained tombstone); one `is_current=1` row remains.
- **Then promotion** (per `COINTEGRATION_BASKET_PROMOTION_PLAN_2026-06-07.md`) operates on this fresh, provenance-complete current run — the parity gate's Tier-2 is now a true bit-exact match. The paused deployment is unblocked.

---
*Read-only plan. Three contained changes (one guard param, one writer UPDATE, one small entrypoint), zero schema/governance/platform impact. Approve to begin, change-by-change, with the §5 tests landing before the CADJPY/USDCHF refresh.*
