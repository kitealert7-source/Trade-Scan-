---
name: rerun-backtest
description: Friction-free rerun of a previously-tested strategy (data refresh, indicator change, engine update, parameter tweak, bug fix) — auto-extends the backtest range, bypasses the Idea Gate with an audited reason, bumps signal_version when required, and supersedes old master_filter rows
---

# /rerun-backtest — Rerun a Tested Strategy Without Fighting the Gates

Use this when the pipeline previously evaluated a strategy and you need to run it again under one of:

| Category     | Trigger                                                              |
|--------------|----------------------------------------------------------------------|
| `DATA_FRESH` | More bars available / baseline is stale. Logic unchanged.            |
| `SIGNAL`     | Indicator definition changed OR a new indicator was added.           |
| `PARAMETER`  | Numeric parameter tweak (no signal-level change).                    |
| `ENGINE`     | Backtest engine code changed; directive is byte-identical.           |
| `BUG_FIX`    | Prior run's result was semantically wrong — old rows get quarantined.|

> **When NOT to use this skill:** if the goal is to verify that a new engine version is correctly wired end-to-end (e.g. confirm charge path, stamp, ledger row on a fresh run), use `/execute-directives` instead. That is a *fresh run*, not a rerun of a prior result. The ENGINE category here means "the directive is unchanged and you want to re-evaluate the same strategy under a different engine" — it still requires a prior run to supersede. If there is no prior run to supersede, you are in `/execute-directives`.

Without this skill, the admission controller's **Idea-Evaluation Gate (Stage -0.20)** refuses the directive with `REPEAT_FAILED` and the **Classifier Gate (Stage -0.21)** blocks indicator changes that don't bump `signal_version`. This skill does the plumbing so legitimate reruns go through first try.

---

## Quick Reference

```bash
# 1. Prepare the rerun directive in INBOX/ (what you'll normally do)
python tools/rerun_backtest.py prepare <target> \
    --category <CATEGORY> \
    --reason "<human explanation, >=20 chars>" \
    [--end-date YYYY-MM-DD]   # default: today
    [--dry-run]               # print planned changes, don't write
    [--force]                 # overwrite existing INBOX directive

# <target> accepts either a strategy name OR an originating run_id:
python tools/rerun_backtest.py prepare 15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00 \
    --category DATA_FRESH --reason "Baseline advanced 6 weeks; max data available"

python tools/rerun_backtest.py prepare 9b3e1a2c4d5f \
    --category SIGNAL --reason "Added liquidity-sweep filter to CHOCH entry model"

# 2. RUN via the governed Golden Path — hand off to /execute-directives.
#    It runs the pipeline AND the capital wrapper + candidate promotion +
#    research-suggestion steps, and enforces "exit 0 != success". A bare
#    single-file dispatch runs Stages 1-4 + promotion but SKIPS the capital
#    wrapper + governance verification — so the new run_id under-populates.
#      /execute-directives   →   python tools/run_pipeline.py --all
#    (the freshly-prepared INBOX directive is the only one queued, so --all
#     picks up exactly this rerun.)

# 2b. VERIFY the rerun actually produced output (the [BATCH] success banner does NOT guarantee it)
#     Assert new backtest dir(s) exist AND new ledger rows landed.
#     If 0 dirs / 0 rows -> STOP, do NOT finalize: the cohort likely resolved to 0 members
#     or pointed at retired/superseded run_ids. (see /execute-directives Step 5.5)

# 3. Finalize — flag old run's master_filter rows as superseded
python tools/rerun_backtest.py finalize \
    --old-run-id <original_run_id> \
    --new-run-id <replacement_run_id> \
    --reason "<CATEGORY>: <short why>" \
    [--quarantine]     # use for BUG_FIX — prevents resurrection
```

---

## Input

The human provides:
- **Target** (required) — strategy name (e.g. `15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00`) OR the originating `run_id`.
- **Category** (required) — one of `DATA_FRESH | SIGNAL | PARAMETER | ENGINE | BUG_FIX`.
- **Reason** (required, ≥20 chars) — why this rerun is legitimate. Lands in the audit log verbatim.
- **End date** (optional) — YYYY-MM-DD. Default: today.

If the category is ambiguous ("I changed the indicator AND bumped a parameter"), pick the most structural one — the order of precedence is `BUG_FIX > SIGNAL > ENGINE > PARAMETER > DATA_FRESH`.

---

## Pre-Conditions

1. The strategy has a recoverable source directive. **Authentic source = the per-run artifact snapshot — look in `TradeScan_State/backtests/<directive_name>/DIRECTIVE_SOURCE.txt` first, then `runs/<run_id>/directive.txt`** (see *Authentic artifact source* below). `prepare` resolves the source via `resolve_baseline` (single-asset `is_current`) first, then via the basket sheets for baskets (`_resolve_basket_source` — F1b), and falls back to the most-recent-mtime scan of `backtest_directives/completed/` → `active_backup/` → `active/` → `archive/` only when neither pins a seed (old/grandfathered runs).
2. No open INBOX entry for the same strategy (use `--force` to overwrite if stale).
3. For `BUG_FIX`, confirm with the human that the old run's result really is wrong before proceeding — quarantining is permanent for analytics purposes (rows stay in the DB, but `filter_strategies.py` never promotes them again).
4. **Re-validating a _contaminated_ identity** — when the prior run is valid-but-wrong (must be *replaced* under its own identity, not compared as a sibling), that run owns the sweep slot + the first-exec anchor, so a same-identity rerun is blocked by `SWEEP_COLLISION` and the preflight EXPERIMENT_DISCIPLINE (first-exec). **Quarantine the prior run first** to release identity ownership while preserving the run (run_id, artifacts, ledger row all survive): `tools/system_registry.quarantine_run(run_id)` frees it standalone (registry `status → quarantined` → sweep slot + first-exec anchor released immediately), or `finalize --quarantine` does the ledger+registry flip once a successor exists. Then rerun under the **original** identity — no orphan slot, no `__E###`-vs-base gymnastics. Capability landed `bc2c8246`; full procedure in the `project_quarantine_lifecycle` memory.

---

## Authentic artifact source — look in `backtests/` first, then `runs/`

See [`reference/artifact_resolution.md`](./reference/artifact_resolution.md).

---

## What `prepare` Does (in order)

// turbo

1. **Resolve target** → strategy name + optional originating run_id (via `master_filter` lookup if given a run_id).
2. **Locate source directive** — searches `completed/` → `active_backup/` → `active/` → `archive/`, most-recent-mtime wins. (`active/` is a legacy / usually-empty dir in the current `INBOX → active_backup → completed` flow — scanned for completeness, rarely the hit.)
3. **Parse YAML**, validate `test:` block shape.
4. **Extend `test.end_date`** to today (or `--end-date` override) for all categories that benefit from fresh data.
5. **Bump `test.signal_version` by 1** for `SIGNAL` and `BUG_FIX` categories — the Classifier Gate (Stage -0.21) requires a strict increment when it classifies the diff as SIGNAL. The bump lands **inside the `test:` block** per `canonical_schema.ALLOWED_NESTED_KEYS["test"]`; any stray root-level `signal_version` from a legacy bad-prepare is defensively stripped.
6. **Inject `test.repeat_override_reason`** with a machine-scannable prefix:
   ```
   [RERUN:<CATEGORY>@<date> origin=<run_id_or_directive-clone> strategy=<name>] <user reason>
   ```
   Guaranteed ≥50 chars so the Idea-Evaluation Gate accepts the override. The user reason lands verbatim after the prefix.
7. **Inject `test.rerun_of`** breadcrumb (originating run_id, if target was a run_id).
8. **Rotate the `__E###` suffix** on filename + `test.name`. The next free integer is allocated by scanning `completed/`, `active_backup/`, `active/`, `archive/`, and `INBOX/` for any existing `<base>__E###.txt`. `test.strategy` always stays at the base stem (family root); only `test.name` and the filename carry the suffix.
9. **Write to `backtest_directives/INBOX/<base>__E###.txt`**.
10. **Audit-log** the event to `outputs/logs/rerun_audit.jsonl`.
11. **Print next-step commands** (pipeline dispatch + finalize invocation template).

---

## Backtest date window — rerun convention

See [`reference/backtest_window.md`](./reference/backtest_window.md). *(The execution-critical `--end-date` gap-pin warning is kept in **Common Pitfalls** above.)*

---

## Run — hand off to `/execute-directives` (do not bare-dispatch)

`prepare` only stages the directive. The actual run goes through
[`/execute-directives`](../execute-directives/SKILL.md) — the same governed Golden Path the
`/hypothesis-testing` spine uses for its run stage — so the new `run_id` is populated
**everywhere** (MPS / candidates, research index, plus the capital profiles for single-asset
reruns) and the governance checks fire ("exit 0 ≠ success", new-rule routing). A bare
`run_pipeline.py <single file>` runs Stages 1-4 + candidate promotion but **skips the capital
wrapper (Step 6) and the verification / research steps** — the new run lands under-populated.

**Ownership split (mirrors the orchestrator spine):**

| Stage | Owner | What |
|---|---|---|
| prepare | this skill | gate bypass + `__E###` rotation + `signal_version` bump → INBOX |
| **run** | **`/execute-directives`** | governed Golden Path: run + capital wrapper + promotion + research + "exit 0 ≠ success" |
| finalize | this skill | supersession (`is_current=0`) / `--quarantine` |
| **retire** | **`/pipeline-state-cleanup`** | trim the predecessor: archive its row → cold parquet + prune its heavy artifacts (per batch, *after* the run) — see *Retire* below |

**A rerun is not a new strategy** — so `/execute-directives`' strategy-*authoring* steps
(Step 1 new_pass creation, Step 2 GENESIS/PATCH/CLONE strategy-admission, Step 3 human
approval) are N/A. **But Step 0 (Directive Admission Gate) still applies** — a `DATA_FRESH` /
extended-`end_date` rerun **must clear the temporal-coverage check** (MASTER_DATA covers the
new window) before dispatch, and Step 4 warmup still runs. The exception is `SIGNAL` /
`BUG_FIX`, where the provisioner patches `strategy.py` and the rerun's **Provisioner 2-Pass
Cycle** (below) applies — let it resolve, then continue the Golden Path.

---

## What `finalize` Does

> **Phase-0 update (2026-06-12, commit `570f6c48`):** for a **declared** rerun
> (`test.repeat_override_reason` present) the `is_current=0` flip on the prior
> `(strategy,symbol)` rows now happens **automatically at Stage-3**
> (`_enforce_master_filter_supersession`). So `finalize` is **no longer required for the
> supersedence flip itself** on declared reruns. It is **still required** for: `--quarantine`
> (BUG_FIX — auto-supersede does **not** quarantine), superseding a run the auto-path did not
> cover, and as the audited explicit/fallback path. It is idempotent against already-auto-
> superseded rows (0 rows flipped, no error).

// turbo

After the pipeline produces a new `run_id`:

1. Validates `--new-run-id` exists in `master_filter`.
2. Calls `ledger_db.mark_superseded(old_run_id, new_run_id, reason, quarantine=...)` which UPDATEs `master_filter` WHERE `run_id = old_run_id AND (is_current = 1 OR is_current IS NULL)`, setting:
   - `is_current = 0`
   - `superseded_by = <new_run_id>`
   - `superseded_at = <UTC ISO timestamp>`
   - `supersede_reason = <category or freeform>`
   - `quarantined = 1` (only with `--quarantine` flag)
3. Audit-logs the flip to `outputs/logs/rerun_audit.jsonl`.

**Append-only invariant preserved** — superseded rows are flagged, never deleted. `filter_strategies.py` filters out `is_current=0` and `quarantined=1` rows from promotion eligibility.

---

## Retire — trim the predecessor (Phase C)

A rerun *replaces* its predecessor; once the new run exists the old run's heavy artifacts are
dead weight — it's `is_current=0`, never promoted, never executed, never a rollback target (that
is the prior *live* config). **Retire it, per batch, strictly *after* the batch's v1.5.10 runs
land:**

1. **Archive the row → cold parquet.** Append the superseded run's compact metrics to
   `TradeScan_State/retired/retired_runs.parquet` (`run_id`, `directive_id`, `engine_version`,
   pair, `test_start/end`, net%/ret_dd/maxDD/trades, `supersede_reason`, `retired_at`). This is a
   queryable **"what-we-tried-and-retired"** table — it feeds the **F19 don't-re-test guard**
   without keeping artifacts.
2. **Drop the live row + prune the artifacts** via
   [`/pipeline-state-cleanup`](../pipeline-state-cleanup/SKILL.md)'s authorized operator-cleanup
   path (the ONLY sanctioned ledger-row drop — Invariant #2). **Archive BEFORE drop** → it is a
   *move* to cold storage, never a destroy. Heavy artifacts (`runs/<run_id>/`,
   `backtests/<name>/`) are pruned; the cold row keeps the numbers.

**Why not earlier:** the predecessor's `directive` + `RECYCLE_RULE_SOURCE.py` are the rerun's
**seed** (the live `recycle_rules/` registry may have drifted, so the capsule snapshot is the only
faithful rule). They must survive until *their own* rerun consumes them — retire is **after**
Phase B, never before.

> **Tool support pending:** the `retire` step (cold-archive writer + authorized drop + artifact
> prune) and the **drift check** (count `is_current=0` runs with un-pruned artifacts not yet in
> `retired_runs.parquet`, surfaced in `/session-close`) are pending tool work in
> `/pipeline-state-cleanup`. Until they land, run retire by hand per batch (exact-`run_id` scope +
> backup discipline); the LOCKED contract below makes it a required part of every rerun.

---

## Gate Behaviour by Category

| Gate                         | DATA_FRESH | SIGNAL | PARAMETER | ENGINE | BUG_FIX |
|------------------------------|:----------:|:------:|:---------:|:------:|:-------:|
| Idea Gate (-0.20)            | bypass     | bypass | bypass    | bypass | bypass  |
| Classifier Gate (-0.21)      | no-diff    | SV↑    | pass      | no-diff| SV↑     |
| Sweep Gate (-0.35)           | idempotent | idem.  | idem.     | idem.  | idem.   |

- **Bypass** = ≥50-char `test.repeat_override_reason` satisfies the override check at `admission_controller.py:143-165`.
- **SV↑** = `signal_version` bumped +1 so classifier's "SIGNAL change without version bump" rule doesn't fire.
- **No-diff** = directive YAML unchanged except for non-signature keys (`test:` block), so the classifier sees no signature change.
- **Idempotent** = sweep registry keys off signature hash; same hash → no reservation churn.

---

## Output to Report

After `prepare`:

| Item              | Value                                   |
|-------------------|-----------------------------------------|
| Strategy          | `<STRATEGY_ID>`                         |
| Category          | `<CATEGORY>`                            |
| Source directive  | `<relative path>`                       |
| end_date          | `<before> → <after>`                    |
| signal_version    | `<before> → <after>`                    |
| Destination       | `backtest_directives/INBOX/<ID>.txt`    |
| Audit log entry   | `outputs/logs/rerun_audit.jsonl`        |

After `finalize`:

| Item              | Value                                   |
|-------------------|-----------------------------------------|
| Old run_id        | `<retired>`                             |
| New run_id        | `<replacement>`                         |
| Rows flipped      | N (master_filter)                       |
| Quarantined       | yes / no                                |

---

## Common Pitfalls

1. **Running `prepare` twice without dispatching the pipeline in between** — both runs succeed because each allocates a distinct `__E###` (the second sees the first sitting in INBOX and picks the next free number). The earlier variant in INBOX still has to be dealt with manually — either dispatch it or delete it before re-running `prepare`, otherwise you have two competing queued reruns.
2. **Forgetting `finalize`** — the new run_id will sit alongside the old one in `master_filter` with no supersession link. Downstream analytics will see both and may double-count. Always finalize once the new run_id is visible.
3. **Wrong category picked** — a `DATA_FRESH` label on what's actually a SIGNAL change will be caught by the Classifier Gate's content-hash check when it goes into production. If you hit a Stage -0.21 block, re-run `prepare` with `--category SIGNAL`.
4. **Using `--quarantine` for non-BUG_FIX** — this permanently excludes the row from promotion. Only use when the prior result is provably wrong (not just "suboptimal").
5. **Trusting the `[BATCH]` success banner on a cloned/retired-cohort rerun** — `run_pipeline` can report `All directives processed successfully` while producing 0 backtest dirs and 0 ledger rows when the cloned cohort points at retired/superseded run_ids. Always check produced-dir-count == directive-count before finalize (2026-06-15).
6. **Gap-/window-sensitive reruns MUST pin `--end-date` by hand** — if the source directive's `end_date` was *deliberately* pinned to dodge a crash bar (e.g. a gap-fill stop-contract crash — PSBRK P17 was end-dated to skip exactly such a bar), the default extend-to-today **re-introduces the dodged bar → the run crashes.** For any window-sensitive rerun pass `--end-date <pinned-date>` explicitly; never let `prepare` silently extend to today. (A genuine full-history / freshness rerun *wants* the extend — the judgement is "deliberate dodge or just stale?". Full convention: `reference/backtest_window.md`.)

---

## Variant Naming Rule (__E### rotation)

See [`reference/variant_naming.md`](./reference/variant_naming.md).

---

## Manual rerun lifecycle (fallback)

If `rerun_backtest.py` is unavailable, see [`reference/manual_lifecycle.md`](./reference/manual_lifecycle.md) for the step-by-step manual sequence.

---

## Stage-3 idempotency + Phase-0 supersession

See [`reference/stage3_supersession.md`](./reference/stage3_supersession.md).

---

## Provisioner 2-Pass Cycle

When `signal_version` or any signature key changes in the directive, the strategy provisioner (called during `exec_preflight.py`) will detect SIGNATURE DRIFT and patch `strategy.py`. This makes `strategy.py` newer than `strategy.py.approved`, triggering EXPERIMENT_DISCIPLINE before the second gate can run.

**Recovery (no abort needed):**

```bash
# After first run pauses at EXPERIMENT_DISCIPLINE:
touch strategies/<ID>/strategy.py.approved
# Copy directive back to INBOX (it was admitted to active_backup)
cp backtest_directives/active_backup/<ID>.txt backtest_directives/INBOX/
# Run again — provisioner finds "signature already up to date", EXPERIMENT_DISCIPLINE bypassed
python tools/run_pipeline.py <STRATEGY_ID>
```

This is expected behaviour for any rerun that changes the STRATEGY_SIGNATURE. Not a failure — do not reset directive state.

> **A directive paused at admission is NOT resumed by `--all`.** Once admitted it sits in
> `active_backup/` at state `INITIALIZED`; a fresh `run_pipeline.py --all` re-scans `INBOX/` and
> trips **`PIPELINE_BUSY`** on the already-admitted directive (and re-queuing a duplicate copy to
> `INBOX/` makes it worse — two competing entries). Resume it by **single-ID dispatch**
> (`run_pipeline.py <directive_id>`), which re-runs the paused directive in place — exactly the last
> line of the recovery above. Only if the state is genuinely stuck (e.g. a ghost `INITIALIZED` after
> a hard kill) does `reset_directive.py <id> --reason ...` clear it first.

---

## ENGINE_OWNED Indicator Removal Pattern

See [`reference/engine_owned.md`](./reference/engine_owned.md).

---

## Sweep Registry Hash Invariant

See [`reference/sweep_hash.md`](./reference/sweep_hash.md).

---

## Related Workflows

| Workflow                         | When to use                                            |
|----------------------------------|--------------------------------------------------------|
| `/execute-directives`            | **Runs the prepared INBOX directive** through the governed Golden Path (run + capital wrapper + promotion + research). The run step delegates here — do not bare-dispatch. |
| `/hypothesis-testing`            | Upstream orchestrator — diverts an *exact re-run* here (§1.0). Use it instead when you want to **compare** a variant (keep both rows), not **supersede** the old one. |
| `/pipeline-state-cleanup`        | Quarterly archival of superseded rows to parquet       |
| `/promote`                       | Promote the new run_id to LIVE after verification      |

---

## Related Files

See [`reference/related_files.md`](./reference/related_files.md).

---

## Rerun Contract (LOCKED — 2026-04-17, amended 2026-05-24, 2026-06-12, 2026-06-14)

See [`reference/contracts.md`](./reference/contracts.md).

---

## System Contract

See [`reference/contracts.md`](./reference/contracts.md).

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| 2026-05-24 | Basket rerun failed: tool wrote `signal_version` at YAML root (KEY COLLISION at test→root mirror, UNKNOWN_STRUCTURE at -0.25), and same-stem filename was refused by `verify_directive_uniqueness_guard`. | `rerun_backtest.py` now (a) bumps `test.signal_version` only and strips stray root key, (b) auto-rotates `__E###` on filename + `test.name`. Same fix applies to non-basket reruns. Regression test: `tests/test_rerun_backtest.py::test_basket_signal_rerun_no_root_collision`. |
| 2026-06-12 | Phase-0 auto-supersede (`570f6c48`) made the finalize / "remove rows first" / `reset_directive` rerun guidance stale; Stage-3 gate is `run_id`-keyed (not `(strategy,symbol)`) and `reset_directive` never touches the ledger. | Rewrote Stage-3 §, added a Phase-0 note to `finalize` §, amended the LOCKED Rerun Contract (auto-supersede declared reruns; `finalize` kept for `--quarantine`/fallback). Verified vs `stage3_compiler.py:414` + `reset_directive.py` (no ledger refs). |
| 2026-06-17 | ENGINE-category engine-verify run routed here instead of execute-directives; "verify wiring on existing strategy" reads as ENGINE rerun but is a fresh run | Add "when NOT to use" contrast vs execute-directives to the ENGINE category row |
| 2026-06-21 | Same-day-crashed bug-fix rerun looped 4 guards; 2-pass recovery misses the preflight first-exec EXPERIMENT_DISCIPLINE check (a crashed run counts as "first ran") | Recovery → FAILURE_PLAYBOOK "same-day crashed base"; root-cause guard fix → SYSTEM_STATE HIGH-ROI proposal |
| 2026-06-24 | ENGINE rerun of a deliberately window-pinned directive (PSBRK P17, end-dated to dodge a gap-crash bar): the default `end_date=today` extend would re-introduce the dodged gap → crash; had to pin `--end-date` by hand. Also: a directive paused at admission isn't re-run by `--all` (sits in active_backup → manual re-queue to INBOX). | Landed 2026-06-29: "Backtest date window" § now warns gap-/window-sensitive reruns MUST pin `--end-date` (extend re-introduces the dodged crash); Provisioner 2-Pass § documents single-ID resume of a paused `active_backup` directive (`--all` trips `PIPELINE_BUSY`). |
| 2026-06-29 | Re-validating a contaminated identity (valid-but-wrong prior run) hit `SWEEP_COLLISION` + first-exec EXPERIMENT_DISCIPLINE — same-identity rerun blocked; worked the multi-guard gauntlet by hand. | Added Pre-Condition #4: quarantine the prior run first (`quarantine_run` / `finalize --quarantine`) to release identity ownership, then rerun under the original identity. Capability `bc2c8246`; procedure → `project_quarantine_lifecycle` memory. |
| 2026-07-02 | Per-symbol rerun rotated `__E###` on the **ledger** name (which carries a `_<SYMBOL>` suffix, e.g. `69_..._P00_SPX500`), so (a) `test.strategy` was non-parseable → `classifier_gate` matched on empty model across families (69 RSIPULL diffed vs a 70 IBS directive → phantom SIGNAL), and (b) doubled `..._SPX500__E001` failed `NAMESPACE_IDENTITY_MISMATCH` at Stage -0.30. Also `resolve_baseline` seed ladder skipped `sandbox/<run_id>/directive.txt`, falling through to the mutable `strategies/<base>/directive.txt` (stale JPN225 seed). Worked around by hand-repairing stems + suffixes E001/E002/E003. | `rerun_backtest.prepare` now derives a canonical base stem (prefers the capsule's own `test.strategy`; peels `__E###` + `_<SYMBOL>` until `parse_strategy_name` accepts it with empty `symbol_suffix`; basket names pass through unchanged) and fails fast if a structured ledger name can't reduce cleanly. `resolve_baseline._resolve_seed` now probes every canonical run home (runs/ → sandbox/ → candidates/) before the strategy working copy. Regression tests: `test_rerun_backtest.py::test_per_symbol_ledger_name_yields_canonical_stem`, `::test_canonical_base_stem_is_idempotent` (fixed-point guard against suffix explosion), `::test_prepare_round_trip_stem_is_stable`; `test_resolve_baseline.py::test_seed_ladder_uses_sandbox_run_home_over_strategy_copy`. |
