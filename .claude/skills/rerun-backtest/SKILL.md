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

---

## Authentic artifact source — look in `backtests/` first, then `runs/`

A rerun's source directive (and the code that ran) is recovered from the per-run artifact
snapshots — **not** by mtime-scanning `completed/`. Look in this order (the same ladder
`resolve_baseline` walks); recent runs' source artifacts increasingly land in `backtests/`, so
**look there first** — it is the most complete and the most natural to hit, since it is keyed
by the directive name (the usual rerun target).

**1 — `backtests/<directive_name>/` — look here first.** Keyed by **directive name**; the
recent-vintage canonical artifact home.

| File | Contents |
|---|---|
| `DIRECTIVE_SOURCE.txt` | byte-exact directive that produced the run — the config to clone (resolver's top rung) |
| `RECYCLE_RULE_SOURCE.py` *(basket)* | the exact leg-rule code that ran |
| `STRATEGY_CARD.md`, `BASKET_REPORT_*.md` / `REPORT_*.md` | human-readable run summary |
| `metadata/`, `raw/` | results (`raw/results_tradelevel.csv`, …) |

**2 — `runs/<run_id>/` — run_id-keyed companion.** When you hold the `run_id` hash, this carries
the same directive plus full sha256 provenance.

| File | Contents |
|---|---|
| `directive.txt` | byte-exact directive snapshot |
| `strategy.py` *(single-asset)* | exact strategy code — write-once (Invariant #4) |
| `basket_code/` *(basket)* | `recycle_strategies.py` + `recycle_rules/*.py` + `code_manifest.json` |
| `manifest.json` | sha256 provenance: `strategy_hash`, `engine_version`, per-leg data + broker-spec sha256, artifact sha256, `execution_mode`, `basket_id` |

**3 — fallback:** `strategies/<id>/directive.txt` → `completed/` → git.

**Why this beats the `completed/` mtime-scan:** these snapshots are keyed to the **exact run**
(by directive name or run_id — the provenance a `run_id`-targeted rerun otherwise discards),
**immutable**, and **sha256-verified** (`runs/.../manifest.json`). You recover the directive
*and* the code that actually ran — not a most-recent-mtime guess that may have landed on a
superseded `__E###` variant.

**`resolve_baseline` walks this exact ladder** — prefer it over hand-scanning:

// turbo

```bash
python tools/resolve_baseline.py <run_id | directive_name | series_tag> --json
# ladder: backtests/<name>/DIRECTIVE_SOURCE.txt → runs/<run_id>/directive.txt
#         → strategies/<id>/directive.txt → completed/ → git   (selects the is_current run)
```

**Coverage caveat:** source capture is recent-vintage — `DIRECTIVE_SOURCE.txt` +
`RECYCLE_RULE_SOURCE.py` are present for ~83% of `backtests/` entries (7,302 / 8,845): basket +
recent runs. Older single-asset `backtests/` entries are **report-only** (no source capture) —
for those the strategy code is in `runs/<run_id>/strategy.py` and the directive falls back to
`completed/`. The captured set grows as new runs land in `backtests/`.

> **Resolution (F1 landed 2026-06-14):** `prepare` resolves the source via `resolve_baseline`
> (`is_current` + the exact per-run seed) **first**, falling back to the mtime scan of `completed/`
> only when the resolver can't pin a single seed. A bare-name target now also captures the
> resolved `is_current` run_id as the `rerun_of` breadcrumb.
> **Baskets (F1b landed 2026-06-14):** baskets live in `cointegration_sheet` / `basket_sheet`,
> not `master_filter`, so `resolve_baseline` can't reach them — `prepare` resolves baskets via a
> dedicated basket-sheet tier (`_resolve_basket_source`): match the `is_current` row by
> `directive_id` / `run_id`, then read the seed from `runs/<run_id>/directive.txt` →
> `<backtests_path>/DIRECTIVE_SOURCE.txt` → `completed/`. Both a basket **name** and an
> **`is_current` run_id** resolve (a basket run_id, absent from `master_filter`, maps to its
> directive via the sheets too). A **superseded** basket run_id is not matched — use the
> directive name or the current run_id; it otherwise falls through to the mtime scan.

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

A rerun runs on the standard recent window, derived from data availability — **not** blindly
from the source directive's original dates:

- **Single-asset:** `start_date` = **2024-01-01**, or the first available bar on/after it (in
  practice **2024-01-02** — 2024-01-01 is a market holiday, no FX bars); `end_date` = the
  **latest available bar** (`min(latest_date)` across the directive's symbols, from
  `data_root/MASTER_DATA/freshness_index.json`). This is exactly what
  `config/backtest_dates.py::resolve_dates(tf, stage="extended")` /
  `governance/preflight.py::resolve_data_range()` already return.
- **Cointegration / basket:** the window is **not** a single 2024→max range — each test is one
  pre-computed cointegrated **span**. Re-run only the spans whose entry falls **within
  [2024-01-01, max]** (drop any with `entry_date < 2024-01-01`); each in-range span stays a
  **separate test** on its own `[entry_date, exit_date]` window. A fixed 2024→max window would
  be **rejected by `window_validity_gate.py`** (the window must be contained in one cointegrated
  span — see [[feedback_test_window_must_match_signal_class]]).

> **Tool support pending — apply by hand for now.** `prepare` today sets `end_date = today` and
> never sets `start_date` (`rerun_backtest.py:474-479`). Auto-setting the single-asset
> `[2024-01-02, max]` window and filtering cointegration spans to the range are **pending tool
> changes** (out of the current skills-only scope). Until they land, set the window per this
> convention when forming / reviewing the rerun directive.

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

---

## Variant Naming Rule (__E### rotation)

A rerun lands as a **new directive variant** of the same family — same `test.strategy` (the base stem), but a freshly allocated `__E###` suffix on the filename and `test.name`. The Idea Gate (-0.20) still bypasses on `test.repeat_override_reason`; the suffix is what satisfies `verify_directive_uniqueness_guard` at `run_pipeline.py:505`, which refuses to re-execute a directive_id already in the registry.

Example:

```
Source:        90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E002.txt
                 test.strategy: 90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100   (base, no suffix)
                 test.name:     90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E002
Rerun output:  INBOX/90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E003.txt
                 test.strategy: 90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100   (unchanged)
                 test.name:     90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E003
```

`reset_directive.py` is **not** required for `__E###`-rotated reruns — the new variant has a distinct directive_id, so PORTFOLIO_COMPLETE on the prior variant doesn't block it. The state file is keyed by filename stem, and the stem now differs.

---

## Manual rerun lifecycle (fallback)

If `rerun_backtest.py` is unavailable, see [`reference/manual_lifecycle.md`](./reference/manual_lifecycle.md) for the step-by-step manual sequence.

---

## Stage-3 idempotency + Phase-0 supersession

> **Rewritten 2026-06-12 — Phase-0 (`570f6c48`) made the old "remove rows first" guidance
> obsolete; the prior text mis-described the gate as `(strategy,symbol)`-keyed.**

Stage-3's skip gate (`stage3_compiler.py:414`) is keyed by **`run_id`** (idempotency — the same
`run_id` is never written twice in a pass), **not** by `(strategy,symbol)` cardinality. A rerun
produces a **new** `run_id` (this is why `finalize` takes distinct `--old-run-id`/`--new-run-id`),
so its rows are **not** skipped — they reach the writer, and Phase-0 resolves the collision there:

- **Declared rerun** (`test.repeat_override_reason` present) → the writer **auto-supersedes** the
  prior `is_current=1` rows for that `(strategy,symbol)`
  (`ledger_db._enforce_master_filter_supersession`). **No manual row removal, no pre-clean.**
- **Undeclared collision** → the writer **raises `MasterFilterCurrencyError` and writes nothing**;
  run `finalize` (`mark_superseded`) on the prior run first, or declare the rerun.

`reset_directive.py` resets pipeline **state files only — it does NOT touch `master_filter` /
`ledger.db`** and is **not** part of rerun row-management. (It is for restarting a directive that
failed mid-pipeline, unrelated to supersession.)

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

---

## ENGINE_OWNED Indicator Removal Pattern

Engine-owned indicators (`volatility_regime`, `trend_regime`, `vol_regime`) are injected by the execution engine at runtime. Strategies must NOT import or call them in `prepare_indicators`. The ENGINE_OWNED_FIELDS guard at Stage-0.5 will block the run with a hard error.

**When removing an engine-owned indicator from a rerun:**

1. Remove from directive `indicators:` list (changes directive hash — update sweep registry)
2. Remove `from indicators.volatility.volatility_regime import ...` from strategy.py imports
3. Remove the call site in `prepare_indicators` (the `vr = volatility_regime(...)` line)
4. Remove from STRATEGY_SIGNATURE `indicators:` array in strategy.py
5. Recompute SIGNATURE_HASH using `_hash_sig_dict` from `tools/strategy_provisioner.py`
6. Update sweep registry hash using `_write_yaml_atomic` (not `new_pass.py --rehash`)
7. If the directive's `volatility_filter` uses `required_regime:`, the Classifier Gate will classify this as SIGNAL (not COSMETIC) — bump `signal_version`

The FilterStack reads `volatility_regime` from the engine context (via `ctx.require('volatility_regime')`), not from the strategy's DataFrame column. Removing the strategy's redundant computation is safe — filter behaviour is unchanged.

---

## Sweep Registry Hash Invariant

The sweep registry `signature_hash`/`signature_hash_full` is the SHA256 of `normalize_signature(parse_directive(<file>))`. It changes when any non-NON_SIGNATURE_KEY in the directive changes.

NON_SIGNATURE_KEYS (do NOT trigger hash change):
- `start_date`, `end_date`, `repeat_override_reason`, `stop_contract_guard`
- All keys under `test:` block that mirror identity: `name`, `strategy`, `broker`, `timeframe`, `description`

Keys that DO trigger hash change (require registry update):
- `indicators:` list (any addition or removal)
- `signal_version:` (bumping for SIGNAL category)
- Any `execution_rules:`, `volatility_filter:`, `trend_filter:`, etc. change

**Never use `new_pass.py --rehash` for patches that already exist in the registry** — it appends a duplicate YAML key instead of updating the existing one. Use `_write_yaml_atomic` directly.

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

| File                           | Location                                         |
|--------------------------------|--------------------------------------------------|
| Artifact snapshot — **look first** | `TradeScan_State/backtests/<directive_name>/` — `DIRECTIVE_SOURCE.txt` + `RECYCLE_RULE_SOURCE.py` (basket) + `raw/` |
| Artifact snapshot — run_id companion | `TradeScan_State/runs/<run_id>/` — `directive.txt` + `strategy.py` \| `basket_code/` + `manifest.json` (sha256) |
| Baseline resolver (`is_current`) | `tools/resolve_baseline.py`                    |
| Rerun tool                     | `tools/rerun_backtest.py`                        |
| Ledger DB + mark_superseded    | `tools/ledger_db.py`                             |
| Idea Gate (Stage -0.20)        | `tools/orchestration/admission_controller.py`   |
| Classifier Gate (Stage -0.21)  | `tools/classifier_gate.py`                      |
| Directive signature schema     | `tools/directive_schema.py`                     |
| Audit log                      | `outputs/logs/rerun_audit.jsonl`                 |
| Overrides audit (Idea Gate)    | `governance/idea_gate_overrides.csv`             |

---

## Rerun Contract (LOCKED — 2026-04-17, amended 2026-05-24, 2026-06-12, 2026-06-14)

- **Variant-rotated reruns** — every rerun gets a fresh `__E###` suffix on filename + `test.name`. `test.strategy` stays at the base stem. `repeat_override_reason` is still the only Idea-Gate bypass.
- **Stage-3 idempotent by `run_id`** *(amended 2026-06-12)* — the compiler skips a *repeated* `run_id`, never a new one; a rerun's new `run_id` writes normally. A collision with a prior `is_current=1` row for the same `(strategy,symbol)` is resolved **at the writer** (Phase-0): auto-supersede for declared reruns, fail-loud otherwise. **No manual row removal** (the prior "remove old rows first" rule is retired).
- **Supersedence is enforced, not optional** *(amended 2026-06-12)* — for a **declared** rerun the prior `run_id` is auto-marked `is_current=0` at Stage-3 (Phase-0, `570f6c48`); `finalize` remains the path for `--quarantine` (BUG_FIX) and as the explicit/fallback. Append-only: flag `is_current=0`, never delete; no auto-overwrite of row identity or metrics.
- **Directive = execution window** — `start_date`/`end_date` in the directive are the authority; no silent clamping by the engine.
- **signal_version lives in test:** — `signal_version` is a child of the `test:` block per `canonical_schema.ALLOWED_NESTED_KEYS["test"]`. Root-level writes collide at the test→root mirror in `pipeline_utils.parse_directive_with_canonical_test` and are also rejected by Stage -0.25 canonicalization. The tool defensively strips any stray root-level key.
- **Cross-skill contract with `/hypothesis-testing`** *(added 2026-06-14)* — the category taxonomy (`DATA_FRESH`/`SIGNAL`/`ENGINE`/`PARAMETER`/`BUG_FIX`) and the supersede-vs-compare boundary are **shared** with the [`/hypothesis-testing`](../hypothesis-testing/SKILL.md) §1.0 divert table, which routes reruns based on them. If either changes here, **review and update `/hypothesis-testing` §1.0 in the same change** — a one-sided edit silently drifts the two skills apart. (Reciprocal of the ownership note in `/hypothesis-testing` §0.)
- **Retirement is part of the rerun** *(added 2026-06-14)* — a rerun is **not complete until its predecessor is retired**: its row archived to `TradeScan_State/retired/retired_runs.parquet` and its heavy artifacts pruned, via [`/pipeline-state-cleanup`](../pipeline-state-cleanup/SKILL.md)'s authorized drop (archive-BEFORE-drop; the only sanctioned ledger-row removal under Invariant #2). Applies to **all** rerun categories. The predecessor's seed (directive + `RECYCLE_RULE_SOURCE.py`) is retired only *after* its rerun consumes it. Keeps the live ledger trim; the cold archive is the don't-re-test record. Enforcement = the `retire` tool step + the `/session-close` drift check (pending).

---

## System Contract

- `master_filter` is append-only. Reruns never delete — they supersede via `is_current=0` (auto at Stage-3 for **declared** reruns since Phase-0 `570f6c48`; via `finalize` otherwise / for `--quarantine`).
- `is_current=1 AND quarantined=0` is the canonical filter for "live, eligible-for-promotion" rows. `filter_strategies.py` enforces this.
- `test.repeat_override_reason` is the ONLY sanctioned Idea-Gate bypass. The tool's auto-prefix is machine-parseable for forensic reconstruction.
- `signal_version` increments are the ONLY sanctioned way to satisfy the Classifier Gate's SIGNAL-diff rule. Never hand-edit it outside this tool.
- Every `prepare` and `finalize` invocation is written to `outputs/logs/rerun_audit.jsonl` — do not bypass the tool with manual YAML edits.

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| 2026-05-24 | Basket rerun failed: tool wrote `signal_version` at YAML root (KEY COLLISION at test→root mirror, UNKNOWN_STRUCTURE at -0.25), and same-stem filename was refused by `verify_directive_uniqueness_guard`. | `rerun_backtest.py` now (a) bumps `test.signal_version` only and strips stray root key, (b) auto-rotates `__E###` on filename + `test.name`. Same fix applies to non-basket reruns. Regression test: `tests/test_rerun_backtest.py::test_basket_signal_rerun_no_root_collision`. |
| 2026-06-12 | Phase-0 auto-supersede (`570f6c48`) made the finalize / "remove rows first" / `reset_directive` rerun guidance stale; Stage-3 gate is `run_id`-keyed (not `(strategy,symbol)`) and `reset_directive` never touches the ledger. | Rewrote Stage-3 §, added a Phase-0 note to `finalize` §, amended the LOCKED Rerun Contract (auto-supersede declared reruns; `finalize` kept for `--quarantine`/fallback). Verified vs `stage3_compiler.py:414` + `reset_directive.py` (no ledger refs). |
| 2026-06-17 | ENGINE-category engine-verify run routed here instead of execute-directives; "verify wiring on existing strategy" reads as ENGINE rerun but is a fresh run | Add "when NOT to use" contrast vs execute-directives to the ENGINE category row |
