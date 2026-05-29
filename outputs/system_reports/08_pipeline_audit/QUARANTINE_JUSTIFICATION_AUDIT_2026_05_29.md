# Quarantine Justification Audit — should the quarantine concept exist at all?

**Date:** 2026-05-29
**Scope:** MPS "Baskets" `quarantine_status` (SUPERSEDED / RETIRED / ARCHIVED_UNRESOLVED / ARCHIVED_DEPENDENCY_LOST)
**Status:** Recommendation on record (Option C); direction decision pending operator.
**Method:** Live read-only DB/Excel inspection + 10-agent audit workflow (per-category inventory → adversarial verify, plus a cross-cutting consumer map and an architectural-grounding agent). No code or schema changes made.

## Context

The original ask was to make operator-applied quarantine tags on MPS "Baskets" rows
**DB-durable** (they live only in Excel and get wiped on pipeline runs). Before building
that, the assumption was **challenged** — under the system's current direction
(deterministic recomputation, minimal authoritative state, preserve *meaning* not artifacts,
remove stale debris), is the quarantine concept still justified, or should it be retired?

This is the read-only audit + recommendation.

## Bottom line

**Recommendation: Option C — retire `quarantine_status` as a persisted artifact and replace
its function with DB-native lineage + already-committed history. Executed as a MIGRATION, not a
deletion. Explicitly NOT Option A.**

- The **concept** (suppress stale/superseded/terminal rows from default views; preserve human
  triage judgment) **earns its place.**
- The **implementation** (a free-text, Excel-only column re-merged each export by
  `ledger_db._merge_audit_columns`) **does not** — it already silently lost 12 of 13
  `ARCHIVED_UNRESOLVED` tags, and the system's newest ledger (`cointegration_sheet`, 2026-05-28)
  was *deliberately built with no quarantine column*, using DB-native `is_current` /
  `superseded_*` / `supersede_kind` instead. That is the precedent to follow.
- Option A (make the free-text quarantine column itself DB-authoritative) is rejected: it would
  duplicate the job of the existing `is_current` / `superseded_*` primitive and re-add derivable
  state the architecture explicitly avoids.
- Option B ("retain a subset of categories") does not apply: **every** category classified
  *archive-elsewhere*, so there is no subset worth keeping in the current form.

## 1. Inventory (live-verified)

DB `basket_sheet`: 649 rows; `is_current` = 478 (1) / 171 (0); `superseded_*` columns 0/649
populated; **no `quarantine_status` column**. Excel "Baskets" exports only the 478 `is_current=1`
rows. Current Excel tags = 110 (368 untagged).

| Category | Rows (Excel) | Origin | is_current | Authority class | Verdict |
|---|---|---|---|---|---|
| SUPERSEDED | 60 (H3_spread 41, cointegration_meanrev_v1_2 16, pine 3) | one-off H3 `leg_direction_flip_bug` rehab 2026-05-25; `superseded_by_run_id` 60/60 | all =1 | historical_lineage | archive-elsewhere |
| RETIRED | 49 (all COINTREV_meanrev) | `tag_retired_cointrev_v1.py`; rule code deleted commit 605317c | all =1 | maintenance_debt | archive-elsewhere |
| ARCHIVED_UNRESOLVED | 1 surviving of **13 intended** (12 already wiped) | H3 Phase-2 terminal-FAIL triage; no replacement lineage | all 13 =1 | historical_lineage | archive-elsewhere |
| ARCHIVED_DEPENDENCY_LOST | 0 | `repair_integrity.py --action mark` soft-tombstone | n/a | maintenance_debt | archive-elsewhere (concept), not delete |

## 2. Consumer analysis

- **Every reader is value-agnostic** (treats any non-empty tag as "tagged") EXCEPT
  `repair_integrity.py`'s DROP path, which preserves only `LINEAGE_PROTECTED_TAGS =
  {SUPERSEDED, ARCHIVED_UNRESOLVED}`. So the 4 values collapse to a **2-way** split
  (protected vs droppable) at most.
- Readers: `cointrev_v1_2_aggregator.py`, `h2_parity_run.py`, `excel_format/styling.py`,
  `state_lifecycle/lineage_pruner.py`, `state_lifecycle/repair_integrity.py`, CI
  `test_quarantine_integrity.py` — **all read from the Excel**, none from the DB.
- `superseded_by_run_id` has **zero functional readers** — pure human-facing provenance, only
  carried forward by `_merge_audit_columns`.
- No runtime consumer hard-breaks if the column vanishes (all guarded). Soft-degrade is
  behaviorally meaningful, though: aggregators silently re-include hidden rows; the pruner
  re-enters the orphan check. Only the **test suites** hard-fail (intended tripwire).

## 3. Counterfactual / reconstruction

- Naive deletion **silently re-admits ~110 `is_current=1` rows** (sign-flipped/retired/terminal)
  into research cohorts, parity, and the operator view — the *opposite* of "remove debris."
  Append-only invariant (CLAUDE.md #2) means rows can't be deleted, only hidden — so a
  suppression flag must exist somewhere.
- "Recomputation is cheap" **does not hold** for this population: Phase-2 explicitly *refused* to
  re-run 13 rows ("brute-force replay … no actionable lineage change"); re-running needed
  directive restore from git; results are `data_vintage`-dependent (a re-run today ≠ the
  historical window).
- Meaning is largely **already durable**: the H3 rehab forensics (`outputs/forensics/
  2026-05-25_h3_rehabilitation/…` manifests) are git-tracked and hold origin→replacement edges +
  triage rationale. RETIRED's reason is a git-commit constant duplicated 4+ places. But **no live
  consumer reads those manifests** — the meaning is stranded outside every code path today.

## 4. Authority review

Quarantine rows are **historical lineage + maintenance debt**, not current research truth.
Their *suppression function* is operationally live (because the rows are `is_current=1`), but the
*free-text tag* is a non-authoritative mirror artifact, structurally doomed to erode.

## 5. URGENT finding — independent of the A/B/C decision

The 12 wiped `ARCHIVED_UNRESOLVED` tags have **already armed a latent hard-abort.** All 13 rows
are `is_current=1` with **no on-disk artifacts**; `lineage_pruner.build_keep_runs` adds untagged
rows to the keep-set, and `verify_referential_integrity` does `sys.exit(1)` on a kept run with
missing disk. The next `lineage_pruner` invocation (via `/pipeline-state-cleanup`) will abort on
those 12 rows. "Nothing broke" only means the pruner hasn't been run since the wipe. This should
be addressed regardless of the chosen option (re-tag from the committed manifest, flip
`is_current`, or fix the pruner's basket arm).

## 6. Recommended direction (Option C via migration — sequence, not detailed design)

This is the *shape*, not a schema design:
1. Migrate hidden-ness onto DB-native lineage on `basket_sheet`: `is_current=0` +
   `superseded_by`/`superseded_at`/`supersede_reason` + a `supersede_kind`/`closure_kind`
   discriminator (mirrors `master_filter.mark_superseded` and `cointegration_schema`). The
   2-way protected/droppable split is all that's functionally needed.
2. Fix `lineage_pruner`'s basket arm so an intentionally-archived (`is_current=0`) no-disk row is
   a valid skip, not a `sys.exit(1)`.
3. Repoint consumers (`cointrev_v1_2_aggregator`, `h2_parity_run`, `styling`, `lineage_pruner`)
   to filter on `is_current` from the DB, as the cointegration ledger already does.
4. Rewrite CI `test_quarantine_integrity` Check A to assert the DB lineage flag, not the
   free-text string.
5. Keep `repair_integrity --action mark` + the value-agnostic pruner skip as a *recomputed*
   orphan safety valve (or convert it to a DB `is_current` flip).
6. Preserve human-judgment meaning as committed history (forensics manifests already exist);
   then retire `quarantine_status` / `superseded_by_run_id` / `quarantine_reason` and the
   `_merge_audit_columns` carry-over.

This supersedes the original "make the quarantine column DB-durable" request: it achieves
durability *and* aligns with the architecture, instead of cementing the wrong primitive.

## Open decision

Which path (Option A keep+DB-authoritative / B subset / C migrate-then-retire), and whether to
handle the urgent `lineage_pruner` exposure first as a standalone fix.
