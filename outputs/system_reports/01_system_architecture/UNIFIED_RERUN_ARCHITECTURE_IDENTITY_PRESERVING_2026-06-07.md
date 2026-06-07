# Unified Rerun Architecture — Identity-Preserving Model (Design Investigation)

**Date:** 2026-06-07
**Type:** Architecture + implementation plan. **No code, no patches, no file changes.**
**Thesis under test:** Replace today's "rerun = new artifact (`__E###` → new directive_id → new run_id → supersession chain)" with "rerun = refresh the evaluation of a stable research object, identity preserved." Verdict below: **the evidence supports the change decisively.**
**Evidence base:** 5 parallel code investigations (write-path, read-path, identity derivation, selection/promotion, governance/reproducibility), file:line-anchored throughout.

---

## Section 0 — The two findings that decide it

- **Superseded ledger rows have ZERO operational consumers.** Every decision path filters to `is_current=1`: promotion gate (`filter_strategies.py:283-284` → `(_is_current==1)&(_quarantined==0)`), basket export (`ledger_db.py:1109` → `query_baskets(current_only=True)` → `WHERE is_current=1 OR NULL` at `:938`), cointegration export/aggregate (`ledger_db.py:1065`, `cointegration_aggregator.py:84` → `WHERE is_current=1`). The **only** reader of `superseded_by` is `family_report.py:265` (diagnostic). Superseded rows are **write-only audit hygiene**, not operational state.
- **Backtests are deterministically reproducible from retained inputs** (manifest pins `strategy_code_sha256`, `directive_sha256`, `parquet_sha256`, `engine_version`, `leg_data_sha256`, `broker_spec_sha256`; no `Math.random`/wall-clock; `strategy.py` write-once; `basket_reproducibility_check.py` tools the comparison). So historical reconstruction — the thing append-only retention was *for* — is achievable from inputs, not from retained superseded rows.

**Conclusion:** the supersession machinery preserves lineage **nothing reads** to enable reconstruction **inputs already guarantee**. It is pure overhead. Remove it; key the operational ledger on a **stable object identity** and **refresh in place**; move lineage to a thin append-only audit log.

---

## Section 1 — Current-state architecture map

**The rerun lifecycle today (`tools/rerun_backtest.py`):** `prepare` (mutate directive: rotate `test.name`+filename → `__E###`, inject `repeat_override_reason` ≥50 chars, bump `signal_version` for SIGNAL/BUG_FIX, extend `end_date`, set `rerun_of`) → run normal pipeline → `finalize` (call `mark_superseded` to flip old rows `is_current=0`).

**Dependency map — every touchpoint:**

| Touchpoint | Role in rerun | Anchor |
|---|---|---|
| `rerun_backtest.py` | prepare/finalize orchestrator; `__E###` rotation; category taxonomy (DATA_FRESH/SIGNAL/PARAMETER/ENGINE/BUG_FIX) | `:259-448`, `:94-136` |
| `generate_run_id` | run_id = sha256(content_hash, symbol, tf, broker, **engine_ver, test.name**, attempt)[:24] — **run_id changes because `test.name` carries `__E###`** | `pipeline_utils.py:278-350` |
| `verify_directive_uniqueness_guard` | rejects re-run of an existing `directive_id` (filename) found in `run_registry` | `run_pipeline.py:505-519` |
| `run_registry` | one entry per run keyed by `run_id`+`directive_id` (filename at exec time) | `system_registry.py:record_run` |
| `mark_superseded` | flips old rows `is_current=0, superseded_by, superseded_at, supersede_reason[, quarantined]` across master_filter + basket_sheet + cointegration_sheet | `ledger_db.py:791-859` |
| `master_filter` / `basket_sheet` | **support** supersession via `mark_superseded` (flip, never delete) | schema + `:835-851` |
| `cointegration_sheet` | **OUTLIER — strict append-only, NO supersession**; rejects duplicate run_id; `supersede_kind` column reserved-but-**unused** | `cointegration_ledger_writer.py:107-124` |
| `classifier_gate` | blocks unless `signal_version` strictly increases when diff classified SIGNAL | `classifier_gate.py` |
| Idea Gate (`admission_controller`) | REPEAT_FAILED block; bypassed by `repeat_override_reason` ≥50 chars | `:147` |
| Stage-3 (`stage3_compiler`) | discovers new run_ids, **appends** (skips existing); no is_current logic; multiple run_ids per strategy coexist | `:361,383` |
| `filter_strategies` | promotion candidate gate — **filters `is_current=1 & quarantined=0`** | `:269-284` |
| `find_run_id_for_directive` | promotion run lookup — scans `runs/*/run_state.json`, **returns FIRST match, is_current-UNAWARE → can promote a stale run** | `pipeline_utils.py:357-410` |
| `promote_to_live` / `yaml_writer` | writes `run_id` into `portfolio.yaml` (static; no auto-update on later rerun) | `promote_to_live.py:172`, `yaml_writer.py:135` |
| Excel export | strips is_current/superseded_*/quarantined before writing xlsx | `ledger_db.py:1141-1144` |
| `rerun_audit.jsonl` | append-only audit of prepare/finalize (category, reason, run_ids, sv) — **survives row drops** | `rerun_backtest.py:252-256` |
| Governance | append-only invariant (AGENT.md #1/#2); operator-cleanup exception via `repair_integrity.py --action drop` | AGENT.md, `repair_integrity.py:1-41` |

**Two latent defects the current model carries:**
- **Stale promotion (real bug):** `find_run_id_for_directive` returns the first run on disk, not the `is_current=1` one → a superseded run can be promoted (`promote_to_live.py:172`). Identity preservation *fixes* this.
- **cointegration can't even do the current model:** its writer is append-only with no supersede, so reruns already pile up duplicate `is_current=1` rows — exactly the friction that motivated this investigation.

---

## Section 2 — Requirements classification

| Feature | Class | Justification |
|---|---|---|
| **`__E###` suffix rotation** | **REMOVE** | The proliferation artifact itself. Exists only to dodge the filename-keyed uniqueness guard. Identity preservation eliminates the need. |
| **`is_current`** | **REMOVE** (operational) | Write-only; every reader filters to `=1`. With one current row per identity (upsert), the flag is vestigial. |
| **`superseded_by` / `superseded_at`** | **REMOVE** (operational) | Chain pointer read by *nothing* operational (only `family_report.py:265` diagnostic). Lineage moves to the audit log. |
| **`supersede_reason` / `supersede_kind`** | **REMOVE** | Never read; `supersede_kind` was reserved-and-never-written. Reason survives in the audit log. |
| **`finalize` step + `mark_superseded`** | **REMOVE** | The two-phase exists solely to flip is_current. Refresh-in-place makes it a single atomic upsert. |
| **`rerun_of`** | **REMOVE from directive/ledger; KEEP in audit log** | Breadcrumb; lineage belongs in the append-only audit, not the operational object. |
| **`quarantine`** | **REMOVE as a supersession flag** | "Never resurrect a bad row" is moot when the bad evaluation is overwritten in place. (If a *directive-level* "do-not-promote" verdict is ever needed, that's a separate disposition field — not row supersession.) |
| **`repeat_override_reason`** | **RECLASSIFY → required refresh `reason`** | The *concept* (an audited human reason) is **Required**; its *form* (a ≥50-char gate-bypass string) is a **legacy artifact**. A refresh is first-class, not a gate-dodge — so the reason becomes a clean audited field on the refresh action. |
| **`signal_version`** | **REQUIRED** | Legitimate evaluation attribute; the classifier gate uses it to detect a *material* signal change that should be Category B (new identity), not a refresh. Keep. |
| **Idea-Gate REPEAT_FAILED block** | **RECLASSIFY** | Must distinguish "**new** object matching a failed pattern" (block) from "**refresh** of an existing object" (allow). The category declares intent; no override-string hack. |
| **Category taxonomy (DATA_FRESH/ENGINE/BUG_FIX/PARAMETER/SIGNAL)** | **REQUIRED** | Drives the A/B split (below) + the audit reason. Keep. |
| **Run provenance (manifest hashes, run_id, runs/<run_id>/ receipt)** | **REQUIRED** | The reproduction substrate. *This* is what retention should protect — not superseded ledger rows. |

---

## Section 3 — Recommended target architecture

### 3.1 The Category A / B split (the conceptual core — and it IS useful)
The `__E###` mess came from conflating two different operations under one word ("rerun"):

- **Category A — REFRESH (identity-preserving).** Same research object, re-evaluated: DATA_FRESH, range-extension, ENGINE bump, BUG_FIX, indicator-fix-to-the-same-strategy. → **same identity, evaluation refreshed in place, no new directive, no variant.**
- **Category B — NEW RESEARCH (new identity).** Materially different signal/methodology/leg-construction/parameter-regime. → **new identity via the *existing* mechanisms** (`_P##` / `_V#` / new directive name / new sweep). This was never really a "rerun"; it's a new object and already has a path.

**Guardrail against B-masquerading-as-A:** the `classifier_gate` + `signal_version` stay exactly for this — if a "refresh" carries a signal diff large enough to be a different strategy, the gate forces it onto the Category-B path (new identity). The operator declares the category; the gate polices it.

### 3.2 Identity model (what is stable vs per-evaluation)

| Identity | Stable or per-eval | Definition |
|---|---|---|
| **Object identity = `directive_id`** | **STABLE** | The logical research object (base stem, **no `__E###`**). A refresh does **not** change it. This is the key the ledger, registry, promotion, and reporting all resolve on. |
| **Strategy/family id = `test.strategy`** | **STABLE** | Family root (already stable today). |
| **Evaluation id = `run_id`** | **PER-EVAL (changes each refresh)** | The provenance receipt — sha256 of inputs+code+engine. It *should* change per refresh; that's correct. It is **not** the object identity. |
| **Operational ledger row** | **STABLE (one per directive_id+symbol)** | **Upserted** on refresh; carries the *current* run_id + metrics + provenance. No second row, no is_current. |
| **Run receipt `runs/<run_id>/`** | **PER-EVAL, immutable, prunable** | Each refresh writes a new receipt (provenance for reproduction). The ledger points at the current one. Old receipts are prunable (reproducible from inputs). |

**Why run_id stays per-eval (not made stable):** making `run_id` stable would break per-evaluation provenance identity and collide with the append-only run_id uniqueness (`cointegration_ledger_writer.py:115`). The right move is the opposite: keep `run_id` as the evaluation receipt, **re-key the ledger/registry/promotion on the stable `directive_id`.** Object identity ≠ evaluation identity.

### 3.3 Rerun execution lifecycle (no variant suffixes, atomic)

```
refresh <directive_id> --category <A-category> --reason "<audited reason>"
   │
   1. validate: directive exists, has a prior run, category is A (else → Category-B path)
   2. append audit entry  (refresh_audit.jsonl: directive_id, category, reason, prior_run_id, ts)  [append-only]
   3. run the NORMAL pipeline on the SAME directive_id
        · uniqueness guard → REFRESH guard: same directive_id + audited reason ⇒ ALLOWED
        · classifier gate still runs (material signal diff ⇒ reject → use Category-B)
        · produces a NEW run_id receipt (runs/<new_run_id>/)
   4. ledger writer UPSERTs the row keyed on (directive_id, symbol):
        refresh metrics + current run_id + provenance   [single atomic write]
   5. registry UPDATEs the existing entry in place (status/timestamps/current run_id)
   6. promotion/reporting resolve directive_id → current run_id deterministically
```

- **Uniqueness → "refresh guard":** re-running an existing `directive_id` flips from *rejected* to *allowed-as-refresh* when an audited Category-A reason is present. New objects still can't silently reuse an id.
- **Stale results "replaced":** by the upsert. No flip, no chain — the row simply *is* the latest evaluation.
- **Atomicity / half-failure:** the upsert commits only on a successful run; a failed refresh leaves the prior row + run_id authoritative. No partial state, no orphan supersession.
- **Operator-error prevention:** required category+reason (audited); classifier gate blocks B-as-A; `find_run_id_for_directive` becomes deterministic (one current run per directive) → **the stale-promotion bug disappears**.

### 3.4 Generalization (one mechanism, all object types) — Task 6
The model keys on `directive_id` + an upsert-by-identity writer — **uniform across single strategies, baskets, cointegration, and any future research object.** Concretely it **fixes the cointegration outlier**: `cointegration_sheet` gets the same upsert-by-`directive_id` path (replacing its append-only-only writer), so a cointegration refresh updates one row instead of piling duplicates. No object-type special-casing — the same `refresh` verb and the same upsert contract everywhere. (This is the right home for the basket/cointegration re-run capability that does not exist today.)

---

## Section 4 — Migration plan (atomic phases)

1. **Phase 1 — Ledger writer: upsert-by-identity.** Add an `upsert_by_directive(directive_id, symbol, row)` contract to the ledger writers (master_filter, basket_sheet, **cointegration_sheet**), replacing append-+-supersede. Keep the columns for now (write current values only). *Reversible; no reads change (all already filter is_current=1).*
2. **Phase 2 — Refresh guard + run lookup.** Change `verify_directive_uniqueness_guard` to allow a same-`directive_id` re-run carrying an audited Category-A reason; make `find_run_id_for_directive` resolve to the **current** run for a directive (kills the stale-promotion bug). Registry `record_run` → update-in-place for a refresh.
3. **Phase 3 — Refresh CLI + audit log.** New `refresh` verb (the identity-preserving successor to `rerun_backtest.py prepare`+`finalize`): one command, category+reason, no `__E###`, no finalize. Append-only `refresh_audit.jsonl` carries lineage (prior→current run_id, category, reason).
4. **Phase 4 — Retire supersession.** Stop writing `is_current/superseded_*/quarantined/rerun_of`; deprecate `mark_superseded` + the `finalize` path; deprecate `__E###` rotation. Columns remain (historical) but become inert.
5. **Phase 5 — Backfill/collapse (optional).** For existing `__E###` chains: keep the latest `is_current=1` as the single current row per object; demote the rest to prunable receipts; record the collapse in the audit log. Drop inert columns in a later schema pass once nothing references them.
6. **Cross-cutting:** Category-B path is **unchanged** (new directive name / `_P##` / sweep). The classifier gate + `signal_version` stay as the A/B guardrail.

---

## Section 5 — Risks, tradeoffs, unresolved questions

**Governance change (the real tradeoff):** the operational ledger moves from *append-only* to *upsert-current-state*, with lineage relocated to an append-only `refresh_audit.jsonl`. This **revises AGENT.md invariant #2** (currently "no overwrite of ledger rows"). The defensible reframing: *the ledger holds current decision-grade state (upsert per identity); a dedicated append-only audit log holds lineage.* Conflating the two is what produced the proliferation. **This invariant change needs explicit operator ratification** — it is the one genuinely load-bearing decision here.

**What is lost by not retaining superseded rows?** Operationally: **nothing** (Section 0 — zero consumers). Forensically: the spreadsheet-level "X→Y, reason Z" — but that **survives in `refresh_audit.jsonl`** (append-only) and the per-run receipts. Reconstruction of any past evaluation: **available from pinned inputs + `basket_reproducibility_check`**. Net loss is a queryable-in-SQL lineage column, replaced by a queryable-in-JSONL audit log. *Document this as the accepted tradeoff.*

**Risks**
- **Receipt retention vs. reproducibility:** if old `runs/<run_id>/` receipts are pruned *and* an input substrate has drifted (e.g., the daily broker-spec YAML before `broker_spec_sha256` pinning), exact reproduction of a pruned past evaluation can fail. *Mitigation:* the provenance pinning just landed; retain receipts until provenance coverage is universal; pruning is a separate, gated op.
- **`portfolio.yaml` staleness semantics:** today a live entry freezes its run_id (no auto-update on later refresh). Under identity preservation a refresh changes the current run_id *under a promoted directive* — decide explicitly whether live entries auto-track the current evaluation or require an explicit re-promote. *Recommend: explicit re-promote stays (a live position should not silently re-point), but promotion now resolves deterministically to the current run.*
- **Audit-log as single point of lineage:** if `refresh_audit.jsonl` is the only lineage record, its durability/backup matters more. *Mitigation:* it is append-only + NAS-backed with the repo.
- **Migration of in-flight `__E###` corpora:** large existing variant chains (e.g., the cointegration corpus) need the Phase-5 collapse to avoid mixed old/new semantics during transition.

**Unresolved questions (for operator)**
1. **Ratify the invariant change** (append-only ledger → upsert-current + append-only audit log)? This gates the whole design.
2. **Receipt-retention policy:** keep every `runs/<run_id>/` receipt indefinitely, or prune to last-N once provenance is universal?
3. **`portfolio.yaml` on refresh:** auto-track current run, or explicit re-promote (recommended)?
4. **BUG_FIX semantics without quarantine:** is "overwrite the wrong evaluation in place" sufficient, or is a separate directive-level do-not-promote disposition ever needed?
5. **Scope of the first cut:** ship the unified `refresh` for all object types at once, or land it on cointegration first (where the current model is already broken) and generalize after?

---

*Design investigation only — no code, no patches, no file changes. All claims are anchored to current source; the one load-bearing decision (the append-only→upsert invariant change) is flagged for explicit ratification.*
