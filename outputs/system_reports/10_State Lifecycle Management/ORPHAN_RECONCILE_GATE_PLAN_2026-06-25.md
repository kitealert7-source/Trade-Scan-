# Orphan-Reconcile Gate — Implementation Plan (PROPOSAL)

**Status:** PROPOSAL — awaiting operator approval. **Protected Infrastructure
(Invariant #6):** `tools/` + gates require an implementation plan + explicit human
approval before modification. Nothing here is self-applied.

**Origin:** 2026-06-25 session retro, HIGH ROI pick. The uncharged-corpus purge
left orphaned live rows in three derived constructs; each was caught by **operator
verification, not by any tool**. This gate converts that manual vigilance into a
mechanical assertion.

---

## 1. Problem

A bulk artifact deletion — and even a single-row drop — can leave **orphaned LIVE
rows** in the derived ledger sheets: rows that assert a disk artifact which no
longer exists. Gating decisions derive from these sheets (Invariant #3, Artifact
Authority), so a stale live row is a silent integrity defect — it shows a
strategy / portfolio / pair as real when its backing run is gone.

`repair_integrity.py` already detects orphans, but two gaps remain:

1. **Coverage is not uniform** across every derived sheet + the 3-tier run store.
2. **It is not run as a post-delete assertion** — it is an operator-invoked
   *repair*, not a gate that *fails* when an orphan exists.

So after a bulk delete nothing mechanically asserts the ledger is still internally
consistent. This session that assertion was performed by the operator, by hand,
three times.

## 2. Evidence (this session — all caught by operator verification)

| Orphan class | What was stale | How it was caught |
|---|---|---|
| Pool move-only runs | `filter_strategies` MOVES `runs/`->`sandbox/` with no junction; the `runs/`-only crawl missed 94 uncharged `sandbox/` runs -> FSP still showed 94 uncharged | operator: "are they all from the new engine?" |
| `portfolio_sheet` DB | `repair_integrity` dropped MPS *xlsx* rows but not the `portfolio_sheet` DB table -> `export-mps` re-emitted them | operator: "PF folders are not deleted, so this will come back again" |
| Elite funnel | the `>=5-runs` criterion broke after the purge (median 1 run/pair) -> 0 elite shown | operator: "does that mean no tests on elite pairs or the list got wiped, check it" |

Each is the same shape: a derived construct that does **not** carry the artifact's
identity, left dangling by a leaf-level delete.

## 3. The dependency graph the gate must walk

Derived live row -> backing artifact it asserts exists:

| Sheet / store | Live-row key | Backing artifact (must exist) |
|---|---|---|
| `master_filter` | (run_id, symbol) | `<run_id>` under any of RUN_DIRS_IN_LOOKUP_ORDER |
| FSP (candidate filter) | run_id | candidates pool run dir |
| `portfolio_sheet`::Portfolios | portfolio_id | `strategies/<portfolio_id>` OR live constituent run_ids |
| `portfolio_sheet`::Single-Asset Composites | portfolio_id | same |
| `basket_sheet` | run_id | `backtests/<directive>_<basket>/raw/results_basket_per_bar.parquet` |
| `cointegration_sheet` | run_id | `backtests_path` |

The run-tier traversal **must** use
`RUN_DIRS_IN_LOOKUP_ORDER = (RUNS_DIR, POOL_DIR, SELECTED_DIR)` — checking only
`runs/` is exactly the bug that missed the 94 `sandbox/` runs.

## 4. Design

A single entry point, two modes:

- **`--audit` (read-only):** scan every sheet/store in S3, emit a structured
  report of every orphaned live row (sheet, key, missing artifact). Exit 0 if
  clean, **non-zero if any orphan** (gate semantics). No mutation.
- **`--repair` (existing drop / mark):** unchanged. The audit is the detection
  half the repair already half-implements per-sheet.

Implementation extends `repair_integrity.py` (it already has `scan_fsp` /
`scan_mps` / `scan_baskets` / `scan_cointegration`). Work: (a) add the missing
sandbox/pool-tier traversal + the `master_filter` scan; (b) unify the per-sheet
scans behind one `audit()` returning the structured orphan list; (c) an `--audit`
CLI that exits non-zero on any orphan.

## 5. Phases (atomic, break-tested)

- **P1 — graph map + audit (read-only):** the `audit()` function + `--audit` CLI
  covering all sheets/stores in S3. No mutation, no wiring. Test: seed one orphan
  per sheet, assert audit reports exactly those + exits non-zero; seed none,
  assert exit 0.
- **P2 — post-delete assertion:** call `audit()` at the end of every bulk-delete
  path, and expose the standalone `python tools/state_lifecycle/repair_integrity.py
  --audit`. A clean exit becomes the deletion's completion criterion.
- **P3 (optional) — standing gate:** run `--audit` in the gate suite or on a
  weekend cadence so cross-session drift is caught, not just post-delete.

## 6. Enforcement mechanism

**Non-zero exit on any orphaned live row.** That is the mechanism — a gate that
*fails*, not a doc that advises. P2 makes "the ledger is consistent" the
*completion criterion* of a delete; P3 makes it a standing check. This is what
converts this session's manual 3x verification into an automated assertion
(satisfies the enforceable-mechanisms-only rule).

## 7. Relationship to the landed wins (commit `4a163498`, 2026-06-25)

- `safe_delete.safe_rmtree()` — the safe *deletion* primitive; cleanup tools
  should adopt it in place of raw `shutil.rmtree`. Companion hardening, separate
  from this gate.
- `repair_integrity.apply_mps_db_drop()` — fixes ONE leak (`portfolio_sheet`).
  **This gate is the general assertion that would have caught that leak + the
  other two automatically.** b2 is a point fix; the gate is the net under all
  future deletes.

## 8. Non-goals

- Not a rewrite of the lineage-aware cleanup workflow (`Workflow_Design.md`) — it
  consumes the same orphan definition and adds the assertion + the missing coverage.
- Not automated deletion — `--audit` never mutates; repair stays operator-driven
  (Invariant #2).
- Not coverage of non-derived stores (`registry/`, `research/`, `reports/`) — only
  sheets that drive gating decisions.

## 9. Open questions for the operator

1. **P2 wiring point:** every cleanup tool calls `audit()` at the end, or a single
   standalone post-purge command the operator runs? (Recommend: standalone command
   first; wire into tools after P1 proves audit is clean-on-green.)
2. **Run-tier traversal cost:** scanning RUN_DIRS_IN_LOOKUP_ORDER over a large
   store is O(rows). Acceptable, or cache the dir listing once per audit?
3. **P3 scope:** gate-suite (every commit) vs weekend cadence? Gate-suite needs the
   audit fast + hermetic (no real-DB dependency) — the existing test-isolation
   fixtures (tmp `LEDGER_DB_PATH`) are the template.
