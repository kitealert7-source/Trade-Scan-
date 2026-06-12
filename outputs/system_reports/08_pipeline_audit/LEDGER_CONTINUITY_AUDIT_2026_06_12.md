# Ledger Continuity Audit — `master_filter.is_current` drift

**Status:** REPORT-ONLY (diagnosis + proposed repair plan). **No ledger mutation, no code change performed.**
**Date:** 2026-06-12. **Trigger:** surfaced by the `resolve_baseline` build review (`b700d42`).
**Grounded by:** workflow `wf_94336ffc-4b6` (4 forensics streams, real `ledger.db` + supersession code).

> **One-line diagnosis.** Supersession (`is_current`) was *retrofitted* onto an append-only
> ledger on 2026-04-16 with a blanket one-pass backfill, and the supersession **step**
> (`finalize`/`mark_superseded`) is **manual, unenforced, and undermined by an unfiltered
> Stage-3 read with no DB guard** — so three eras of damage accumulated.

---

## 1. Scope (corrected)

Not 468 — **882 strategies have no `is_current=1` row** (468 was only Bucket A). Four classes:

| Class | Count | State | Meaning |
|---|---:|---|---|
| **A1** broken chains | 3 | `is_current=0`, `superseded_by` → an `is_current=0` run | transitive supersession failure |
| **A2** orphans | 465 | `is_current=0`, `superseded_by=NULL` | retired, **no successor recorded** |
| **B** legacy NULL | 412 | all rows `is_current=NULL` | never backfilled to 1 |
| **C** mixed | 2 | some symbols `0`, some `NULL` | partial multi-symbol supersession |
| **NULL+1 hybrids** | 2 | one `is_current=1` **and** one `NULL` for same (strategy,symbol) | legacy NULL never reconciled |

Dominant cohorts: `53_MR` (396), `68_PORT` (65). A2 spans 2020→2026; B spans 2021→2024-09.
Concrete examples — broken chain: `139baa31…` → `b504f8e1…` (both `is_current=0`; target marked
`STATE_LOST` 2026-05-21 but `139…` never re-pointed). Hybrid: `22_CONT_FX_30M…S02_V1_P03/EURAUD`
has `74f2c63d…`(NULL) alongside `8e41b97a…`(is_current=1).

---

## 2. Root causes

**RC1 — Retrofit backfill assumption (the origin).** `is_current` was added in commit `0243d1a3`
(2026-04-16); schema created `824dbf6c` (2026-04-12). The migration ran a single
`UPDATE … SET is_current=1 WHERE is_current IS NULL` (`ledger_db.py:359-368`), assuming **every**
legacy NULL row is the current one. Any strategy re-run in the 2026-04-12→15 window had **all** its
rows backfilled to `1` → multi-current. SQLite's `ALTER TABLE ADD COLUMN` ignores `DEFAULT` for
existing rows, so the one-pass backfill was load-bearing — and it missed rows written by code paths
that omit `is_current` (→ Bucket B NULL slippage).

**RC2 — Manual, unenforced supersession.** `mark_superseded()` is invoked **only** by the
`rerun_backtest.py finalize` subcommand (`:421-426`); `run_pipeline` **never** auto-calls it. Forget
`finalize` → old rows stay `is_current=1` (multi-current / NULL+1). Skip it for one symbol of a
multi-symbol strategy → that symbol orphaned (Bucket C). The 3 broken chains (A1) are RC2 in time:
`finalize` superseded `A→B` on 2026-05-12, then `B` itself was archived (`STATE_LOST`) on
2026-05-21 with **no transitive re-point** of `A→C`.

**RC3 — No guard + unfiltered Stage-3 read.** PK is `(run_id, symbol)`; there is **no** UNIQUE/CHECK
preventing two `is_current=1` rows per `(strategy, symbol)`. `stage3_compiler` builds its
`existing_ids` from `read_master_filter()` (`ledger_db.py` `query_master_filter`, **no** `is_current`
filter), so it can't distinguish live from superseded, and a fresh INSERT defaults `is_current=1`.

> **Elegant connection:** the `query_master_filter_current()` helper just added for `resolve_baseline`
> (`b700d42`) is *exactly* the fix Stage-3 needs (RC3). The resolver work feeds the repair.

---

## 3. Proposed repair plan (REPORT-ONLY — operator-approved, append-only, dry-run-first)

### Phase 0 — Stop the bleeding (CODE; prerequisite for wiring skills)

| # | Change | Risk |
|---|---|---|
| P0.1 | `stage3_compiler` existing-ids read: `read_master_filter()` → **`query_master_filter_current()`** | low (helper exists, used by resolver) |
| P0.2 | Guard in `upsert_master_filter_df`: refuse/log a 2nd `is_current=1` for an existing `(strategy,symbol)` (or partial-UNIQUE index on SQLite ≥3.39) | low–med |
| P0.3 | Auto-supersede on rerun completion (or **fail-loud**): pipeline marks prior `(strategy,symbol)` rows superseded **transitively** when a rerun lands — closes the manual-`finalize` gap | med (needs correct run ordering) |

Phase 0 makes the invariant hold **going forward**, so the resolver (and the skills that will depend
on it) sit on clean truth. **This is the real prerequisite for skill wiring — not Phase 1.**

### Phase 1 — Reconcile existing damage (DATA; new `reconcile_master_filter.py`, dry-run + audit log; append-only — flag, never delete)

Per `(strategy, symbol)` group:
- **NULL-only (Bucket B):** promote the latest NULL row to `is_current=1`; demote older NULL siblings to `0`, `superseded_by=latest`, reason `LEGACY_BACKFILL`.
- **NULL+1 hybrids (2) & Bucket C:** an explicit `is_current=1` exists → demote the NULL/extra rows to `0`, `superseded_by=the-1`, reason `LEGACY_BACKFILL`. *(Also clears the resolver's append-only false-positive.)*
- **Multi-current (>1 `is_current=1`):** keep the latest, demote the rest, reason `RETROFIT_DEDUP`.
- **A2 orphans (465):** **do NOT guess successors** (high-risk). They are correctly excluded today. Optionally set `quarantined=1` for intent-clarity; otherwise leave as the truthful "retired, no live successor."
- **A1 chains (3):** investigate the **2026-05-21 `STATE_LOST`** event first. Legitimate → leave (no live version is the truth); a bug → the strategy needs a fresh run, not a fabricated pointer.

### Phase 2 — Re-audit
Re-run this audit. Expect **0 multi-current, 0 NULL**, with the only remaining "no `is_current=1`"
being genuinely-retired strategies (A1/A2 with no live successor) — which is correct, not drift.

### Rejected options (do not pursue)
- **DELETE orphaned rows** (D2) — violates append-only.
- **Blanket `UPDATE … NULL→1`** (D4) — would resurrect superseded rows; must be per-group.
- **Truncate + recompile** ("nuclear", D4) — append-only violation + run_id churn.

---

## 4. Open questions for the operator
1. Was the **2026-05-21 `STATE_LOST`** event (which orphaned the 3 `67_PORT` chains) legitimate or a bug? (Decides A1 treatment.)
2. For **Bucket B (412 NULL)**, which prefixes (`01_MR`, `41_REV`, `68_PORT`) are still live vs. truly legacy? (Decides promote-vs-retire.)
3. Should A2 orphans (465) be `quarantined=1` for clarity, or left as-is?
4. Does `portfolio.yaml` override `is_current` for promoted strategies (could a LIVE strategy be `is_current=0`)?

---

## 5. Bottom line
The 4,000 directives were never the problem; they were the symptom that led here. The disease is a
**retrofitted supersession model with a manual, unguarded enforcement step.** The resolver already
degrades gracefully over this mess (returns `resolved:false` / errors truthfully), so it is safe to
ship — but **Phase 0 should land before the skills are taught to depend on the ledger**, so the
continuity infrastructure rests on an invariant that is actually enforced.
