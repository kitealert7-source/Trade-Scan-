# Cointegration Identity-Preserving Refresh — Pilot Plan

**Date:** 2026-06-07
**Status:** Read-only plan. Protected infra (`tools/` + ledger schema + a governance invariant) → **Phase 0 governance ratification + per-phase approval required before any code.**
**Lineage:** Decision below supersedes the scope of `UNIFIED_RERUN_ARCHITECTURE_IDENTITY_PRESERVING_2026-06-07.md` + its adversarial `…_VALIDATION_…`.

## Decision (operator, 2026-06-07)
- **REJECT** the platform-wide rerun redesign for now — too much scope (the validation showed 3 PK migrations, a charter-level 5-invariant change, and live-promotion blast radius).
- **ACCEPT** identity-preserving reruns as the future direction.
- **IMPLEMENT** the **cointegration-first pilot only.**

**Why cointegration is the ideal pilot (the favorable accident the adversarial pass found):**
- It **already lacks proper supersession** — `cointegration_sheet` is append-only with no `mark_superseded` path, so a rerun today produces *duplicate* `is_current=1` rows (a bug). The pilot **adds** a clean refresh; it does **not** have to *unwind* anything.
- **Zero live exposure** — cointegration is research-only (0 LIVE positions). A mistake can't touch a live book.
- **Isolated blast radius** — its own ledger table + its own consumers; `master_filter`/promotion/vault/composite are untouched.
- **Minimal schema cost** — `cointegration_sheet` already carries a `directive_id` column (`cointegration_schema.py:46`), so the master_filter blocker ("no directive_id column") does **not** apply here.

## Scope
**IN:** `cointegration_sheet` refresh-in-place (replace-by-`directive_id`); a first-class `refresh` path with category+reason; uniqueness-guard refresh-awareness (cointegration-scoped); an append-only `cointegration_refresh_audit.jsonl`; window-match-safe span re-derivation; first real use = CADJPY/USDCHF → promotion.
**OUT (explicitly):** `master_filter` + `basket_sheet` (untouched, stay append-only); **`quarantine` (carved out per validation §5.1 — a separate, live-consumed disposition system; not touched)**; the platform-wide redesign; any LIVE-promotion-ledger change; `runs/<run_id>/` receipt pruning (receipts retained).

---

## Phase 0 — Governance ratification (HARD GATE, no code before this)
Ratify a **narrow, research-only** invariant exception and document it in AGENT.md + CLAUDE.md:
> `cointegration_sheet` (research-only, 0 LIVE) moves from *append-only* to **refresh-replace-by-`directive_id`** (current-state per object). Lineage relocates to the append-only `cointegration_refresh_audit.jsonl`. The append-only mandate (Inv. #1) and run-id-stamped-conclusions (Inv. #31) remain in force for `master_filter`/`basket_sheet` and for the audit log + per-run receipts (which stay immutable). Atomicity (Inv. #2): the replace commits only on a successful run.

This is the one mandatory governance change, and it is **scoped to the pilot table** — not the charter-wide change the user rejected. **Requires explicit operator sign-off.**

## Phase 1 — `cointegration_sheet` refresh writer
Replace the append-only-FATAL-on-duplicate path (`cointegration_ledger_writer.py:115-124`) with **refresh-replace-by-`directive_id`**: on write, `DELETE FROM cointegration_sheet WHERE directive_id=?` (the prior evaluation row) then `INSERT` the new evaluation. **No PK migration** (run_id stays the row PK; identity is enforced by the delete-by-`directive_id` step). `is_current` stays constant `=1` (no `is_current=0` rows ever accumulate → readers unaffected). The prior `runs/<old_run_id>/` receipt is **retained** (reproducibility). → *Exit: a rerun of a cointegration directive yields one current row, not a duplicate.*

## Phase 2 — First-class `refresh` path
A `refresh <directive_id> --category <DATA_FRESH|ENGINE|PARAMETER|BUG_FIX> --reason "…"` flow that:
1. **Window-match-safe span re-derivation** (the load-bearing cointegration detail, per `feedback_test_window_must_match_signal_class`): for DATA_FRESH/extend, re-derive the pair's **current cointegrated span** from the screener (NOT a blind extend-to-today) so `window_validity_gate` passes; for ENGINE, reuse the recorded window.
2. Re-run through the **normal pipeline** — the uniqueness guard (`run_pipeline.py:505`) is made **refresh-aware**: a declared, audited cointegration refresh of an existing `directive_id` is **allowed** (it is not a "new object reusing an id"). Produces a new `run_id` (records `broker_spec_sha256`, post the provenance fix `8ee1b87e`).
3. Writes via the Phase-1 refresh writer (replace-by-`directive_id`).
4. Appends to the append-only `cointegration_refresh_audit.jsonl` (directive_id, category, reason, prior_run_id → new_run_id, ts). Atomic: the replace commits only on a successful run; a failed refresh leaves the prior row authoritative.

→ This is the proper first-class re-run the codebase lacks for cointegration — **not** the promotion-tool bypass I was (rightly) corrected on.

## Phase 3 — Reader sanity (scoped)
Confirm cointegration consumers stay correct under refresh-replace: `cointegration_aggregator.py:84` + `trade_candidates_view.py:114-123` read `is_current=1` → always exactly one current row per directive → per-pair runs-count stays **honest** (counts distinct directives, never refresh-inflated; `MIN_QUALIFYING_RUNS>=5` semantics preserved). Note the one graceful loss: `prior_run_delta.py` has no cointegration prior-row source under replace (lineage now lives in the audit log + receipts) — it degrades to "no prior" cleanly.

## Phase 4 — First real use → unblocks promotion
`refresh 90_PORT_CADJPYUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS__E260312 --category DATA_FRESH --reason "capture broker_spec provenance + current span"` → fresh run recording `broker_spec_sha256`, one clean upserted row, `74d26f18407d`'s receipt retained. This produces the parity-clean, provenance-carrying artifact the **basket promotion plan** needs — closing the loop on the paused CADJPY/USDCHF deployment.

---

## Validation §5 conditions — applied
- ✅ Quarantine **carved out** (untouched).
- ✅ No `master_filter` change; no schema PK migration (delete-by-directive avoids it).
- ✅ Receipts retained (reproducibility + `basket_reproducibility_check`).
- ✅ Window-match-safe (the memory-hint discipline).
- ✅ Scoped invariant ratified (Phase 0), not the rejected charter-wide change.
- ✅ Cointegration-first; `master_filter`/baskets explicitly later/never under this plan.

## Risks / rollback
- **Research-only**, 0 LIVE — a mistake is contained. Rollback = restore the append-only writer; the refresh audit log + retained receipts preserve any lost lineage.
- **The replace deletes a research ledger row** — mitigated by the append-only audit log + retained `runs/<run_id>/` receipt + deterministic reproducibility.
- **Uniqueness-guard refresh-awareness** must be tightly scoped to *declared cointegration refresh* so it can't silently let a genuine new object reuse an id.

---
*Read-only pilot plan. Phase 0 (governance ratification) is the gate; nothing builds before it.*
