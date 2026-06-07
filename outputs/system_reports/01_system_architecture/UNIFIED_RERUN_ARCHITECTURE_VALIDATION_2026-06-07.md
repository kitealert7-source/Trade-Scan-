# Identity-Preserving Reruns — Adversarial Validation

**Date:** 2026-06-07
**Companion to:** `UNIFIED_RERUN_ARCHITECTURE_IDENTITY_PRESERVING_2026-06-07.md` (the proposal under test)
**Mandate:** Break the proposal. Read-only; no code/patches/changes.
**Result:** The proposal does **not** survive intact. Its core direction is sound, but its central claim is falsified and three structural costs were materially understated. **Verdict: APPROVE WITH CHANGES** (§5).

---

## Section 1 — Proposal weaknesses discovered

1. **"Superseded rows have ZERO operational consumers" is FALSE.** The prior read-path pass searched `is_current`/`superseded_by` and missed the adjacent governed concepts. Real consumers exist (§2). The accurate, narrower claim that survives: *the `is_current=0` rows produced by a **rerun** are not read by the **promotion/candidate-selection** decision path* — but they ARE read by reporting, and the proposal wrongly swept in `quarantine`, which is a different, well-consumed system.

2. **`quarantine` was misclassified as REMOVE — it is a live, separately-consumed disposition system, NOT rerun-supersession.** Conflating the two is the proposal's biggest error. Quarantine has ~6 consumers + 2 CI guards (§2). It must be **kept** and **decoupled** from the rerun redesign entirely.

3. **"Upsert-by-identity" was presented as a writer change; it is a multi-table SCHEMA MIGRATION.** `master_filter` has **no `directive_id` column at all** (PK = `(run_id, symbol)`); `basket_sheet` and `cointegration_sheet` are **PK = `run_id`**; the basket/cointegration writers raise FATAL on duplicate run_id; Stage-3 skips by run_id. None can upsert-by-directive without re-keying + writer refactor + Stage-3 surgery (§3). The proposal's "Phase 1 writer upsert" is not a writer-local change.

4. **Making `run_id` ephemeral surfaces several stable-key bindings the proposal didn't address** — composite `constituent_run_ids`, `vault_id = …__{run_id[:8]}`, `portfolio.yaml run_id`/`promotion_run_id` + its uniqueness check, `get_active_portfolio_runs` (§2). Some pre-exist the proposal, but it makes them first-class.

5. **The candidate-tab runs-gate coupling was missed.** `trade_candidates_view` counts runs per *pair* with `MIN_QUALIFYING_RUNS>=5` over `is_current=1` rows. Steady-state the identity model actually *improves* this (honest counts, not refresh-inflated) — but the **migration-time collapse of existing `__E###` chains** could drop rerun-heavy pairs below the gate. A real migration caveat the proposal didn't flag.

6. **Governance surface understated.** The proposal named one invariant (#2). The real surface is **5 mandatory + 1 avoidable** (§3).

---

## Section 2 — Hidden dependencies discovered

**Quarantine (the big miss) — KEEP, do not remove:**
- `excel_format/styling.py:384-402` — **hides** `quarantine_status` rows in the Excel views (the only non-deletion way to hide obsolete rows).
- `lineage_pruner.py:210-234` — `_row_is_quarantined()` makes `build_keep_runs` **skip** quarantined rows (so they aren't pruned as orphans).
- `cointrev_v1_2_aggregator.py:35-46` and `h2_parity_run.py:177-195` — **filter out** quarantined rows by default in reporting/parity.
- CI guards: `test_quarantine_integrity.py`, `test_lineage_pruner_quarantine_filter.py` — break if the columns vanish.

**`is_current` / `superseded_by` readers (beyond the promotion filter):**
- `report/prior_run_delta.py:144-178` — **deliberately reads `is_current=0`** ("the historical metric is still a fact") to render "prior run superseded" on family reports. Degrades gracefully (returns None) but is a real reader.
- `cointegration_aggregator.py:84` — `WHERE is_current=1`; removing `is_current` forces this (and the whole cointegration reporting corpus) to change.
- `cleanup_reconciler` / `lineage_pruner` — traverse supersession state.

**`governance/supersession_map.yaml`** — read by `family_report.py:235-271` for family-rename diagnostics; governed by a pre-commit append-only hook + `test_supersession_map_append_only.py`. *(Note: this is FAMILY-rename lineage, orthogonal to run-row supersession — the proposal didn't propose removing it, but the naming overlap must not cause collateral damage.)*

**run_id-as-stable-key bindings (break when run_id changes per refresh):**
- `promote/decomposition.py:36-98` — composite `constituent_run_ids` go stale; fallback fails if the old receipt is pruned.
- `promote_to_live.py:179-181` — `vault_id` baked from `run_id[:8]`; refresh orphans the vault and (`validate_portfolio_integrity.py:95-104`) can trip LINEAGE_MISMATCH.
- `yaml_writer.py:135-138` + `promote_to_live.py:283-314` — portfolio.yaml run_id uniqueness check can flag a post-refresh duplicate/stale.
- `pipeline_utils.py:357-410` `find_run_id_for_directive` returns the **first** run, not the newest → **already a stale-promotion bug**, worsened by ephemeral run_ids (the identity model can *fix* this if it resolves to the current run).

**Consumers that need >1 row/run per directive:**
- `trade_candidates_view.py:114-123` — per-pair `runs>=5` gate (ledger rows; migration caveat, §1.5).
- `basket_reproducibility_check.py:41-60` — needs **multiple receipts** per directive, but reads `runs/<run_id>/manifest.json` on **disk** → fine if receipts retained; **receipt-pruning is the blocker**, not ledger upsert.
- `research_memory` indices cross-reference run_ids → orphaned references (semantic, not runtime).

---

## Section 3 — Required governance changes (AGENT.md invariants)

| Invariant | Conflict | Class |
|---|---|---|
| **#1 Ledger Supremacy / append-only** | Upsert overwrites rows — direct contradiction; the `repair_integrity --drop` exception model must be re-specified | **MANDATORY** |
| **#2 Fail-Fast** | Upsert must be atomic — a half-failed refresh must NOT overwrite the prior row with partial state | **MANDATORY** |
| **#3 Artifact Authority** | If the refresh overwrites `backtests/<directive_id>/`, gating-from-physical-artifact is compromised; must retain or re-base gating | **MANDATORY** |
| **#9 Append-Only Audit** | The new lineage audit log becomes the sole lineage source — it must itself be append-only + protected | **MANDATORY** |
| **#31 Pipeline-Authoritative Conclusions** | Each ledger row / audit entry must stay **run_id-stamped** so conclusions trace to their evidence | **MANDATORY** |
| **#4 Snapshot Immutability** | New run_id ⇒ new write-once snapshot — **preserved** as long as refresh never rewrites an existing `runs/<RUN_ID>/` | **AVOIDABLE** (confirm design) |
| #6 Directive Integrity / #8 Single Authority / #10 Human Gating | Only conflict if the refresh is an out-of-`run_pipeline` tool or auto-triggered without re-gating — keep it pipeline-internal + manual | **OPTIONAL** |

**Net:** this is a **governance-charter-level change** (5 mandatory invariants), not a one-line edit to #2. It requires an explicit, written invariant revision + operator ratification before any implementation.

---

## Section 4 — Recommended rollout order

**Option A — Cointegration-first pilot ✅ RECOMMENDED.**
- **Blast radius: lowest.** Cointegration is research-only (0 LIVE positions); `cointegration_sheet` has **no supersession at all today** → the redesign is near-greenfield there (nothing to unwind), and it is exactly where the current model is already broken.
- **Rollback: easy.** A research-only ledger; revert = restore the append path. No live promotion depends on it.
- **Validation quality: high.** Exercises the full upsert-by-`directive_id` contract (the cointegration writer already carries `directive_id`) on a real, contained corpus before touching the promotion-critical `master_filter`.
- **One thing it still touches:** the `trade_candidates_view` per-pair runs gate reads `cointegration_sheet` — so the pilot must pin the gate's "run" definition to **distinct directive**, not row-count, and handle the `__E###` collapse. Contained and explicit.

**Option B — Full unified rollout ✗.**
- Touches `master_filter` (no `directive_id` column; feeds LIVE promotion, composite, vault) + 3 PK migrations + every reader at once. **Blast radius: maximal; rollback: hard; migration: complex.** Defer `master_filter` to last, after the cointegration pilot proves the contract.

**Recommended order:** (1) cointegration pilot with the §5 changes → (2) baskets → (3) `master_filter` last (the schema re-key + the promotion/vault/composite refactor), each gated on the prior proving clean.

---

## Section 5 — Final verdict

### APPROVE WITH CHANGES

**Why not REJECT:** the core thesis holds — `__E###` proliferation is real cognitive/operational cost; rerun-supersession *rows* genuinely don't drive promotion/candidate decisions (they're filtered to `is_current=1`); reproduction is deterministically tooled. Identity-preserving refresh is the right direction, and cointegration *needs* it (its model is already broken).

**Why not APPROVE as-written:** the proposal's "zero consumers / trivial writer change / one invariant" framing is falsified — quarantine is a live system, upsert is a multi-table schema migration, run_id bindings break, and the governance surface is charter-level.

**Required changes (conditions of approval):**
1. **Decouple `quarantine` from the redesign entirely** — it is a separate disposition system with real consumers; **keep it untouched.** Only retire the rerun-supersession *rows* (`is_current/superseded_by/superseded_at/supersede_reason` written by `mark_superseded`), not quarantine.
2. **Re-scope "upsert" honestly as a schema migration:** add `directive_id` to `master_filter`; choose the upsert key per ledger (`directive_id` ± `symbol`/`basket_id`); refactor the append-only writer guards + Stage-3's skip-by-run_id. High effort, structural.
3. **Migrate the `is_current` readers** (`prior_run_delta`, `cointegration_aggregator`) before dropping the column; don't delete columns until readers are migrated.
4. **Define the run_id-binding refactor** (vault_id off `directive_id` or a seq; composite + portfolio.yaml resolve current-run-by-directive; fix `find_run_id_for_directive` to return newest). This *also fixes the existing stale-promotion bug.*
5. **Pin the candidate-gate's "run" to distinct directive**, and handle the `__E###` collapse at migration so rerun-heavy pairs don't fall below `>=5`.
6. **Write the invariant revision** (#1/#2/#3/#9/#31) and get explicit operator ratification — this is a governance-charter change, gated before implementation.
7. **Receipt-retention guarantee:** keep `runs/<run_id>/` receipts (reproducibility + `basket_reproducibility_check` depend on them); treat pruning as a separate, later, gated policy.
8. **Roll out cointegration-first** (§4).

**One-line:** *The idea is right and worth doing; the proposal under-costed it by ~3×. Approve the direction, but only with quarantine carved out, the schema migration owned honestly, the run_id bindings refactored, and a real invariant revision — piloted on cointegration before it touches the live promotion ledger.*

---
*Adversarial validation — read-only; no code, no patches. All findings file:line-anchored to current source.*
