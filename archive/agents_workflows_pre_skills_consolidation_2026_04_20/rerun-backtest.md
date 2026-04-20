---
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

# 2. Dispatch the pipeline against the freshly-prepared directive
python tools/run_pipeline.py backtest_directives/INBOX/<STRATEGY_ID>.txt

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

1. The strategy has a directive in one of: `backtest_directives/completed/`, `active_backup/`, `active/`, or `archive/`. The tool searches most-recent-first across all four.
2. No open INBOX entry for the same strategy (use `--force` to overwrite if stale).
3. For `BUG_FIX`, confirm with the human that the old run's result really is wrong before proceeding — quarantining is permanent for analytics purposes (rows stay in the DB, but `filter_strategies.py` never promotes them again).

---

## What `prepare` Does (in order)

// turbo

1. **Resolve target** → strategy name + optional originating run_id (via `master_filter` lookup if given a run_id).
2. **Locate source directive** — searches `completed/` → `active_backup/` → `active/` → `archive/`, most-recent-mtime wins.
3. **Parse YAML**, validate `test:` block shape.
4. **Extend `test.end_date`** to today (or `--end-date` override) for all categories that benefit from fresh data.
5. **Bump `signal_version` by 1** for `SIGNAL` and `BUG_FIX` categories — the Classifier Gate (Stage -0.21) requires a strict increment when it classifies the diff as SIGNAL.
6. **Inject `test.repeat_override_reason`** with a machine-scannable prefix:
   ```
   [RERUN:<CATEGORY>@<date> origin=<run_id_or_directive-clone> strategy=<name>] <user reason>
   ```
   Guaranteed ≥50 chars so the Idea-Evaluation Gate accepts the override. The user reason lands verbatim after the prefix.
7. **Inject `test.rerun_of`** breadcrumb (originating run_id, if target was a run_id).
8. **Write to `backtest_directives/INBOX/<strategy>.txt`**.
9. **Audit-log** the event to `outputs/logs/rerun_audit.jsonl`.
10. **Print next-step commands** (pipeline dispatch + finalize invocation template).

---

## What `finalize` Does

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

1. **Running `prepare` twice without dispatching the pipeline in between** — the second `prepare` will refuse because the INBOX file exists. Use `--force` only if you intend to discard the first prepare.
2. **Forgetting `finalize`** — the new run_id will sit alongside the old one in `master_filter` with no supersession link. Downstream analytics will see both and may double-count. Always finalize once the new run_id is visible.
3. **Wrong category picked** — a `DATA_FRESH` label on what's actually a SIGNAL change will be caught by the Classifier Gate's content-hash check when it goes into production. If you hit a Stage -0.21 block, re-run `prepare` with `--category SIGNAL`.
4. **Using `--quarantine` for non-BUG_FIX** — this permanently excludes the row from promotion. Only use when the prior result is provably wrong (not just "suboptimal").

---

---

## Same-Stem Rerun Rule

A rerun uses the **same directive filename** as the original (`strategy_id` unchanged). The pipeline differentiates original from rerun **only** via `test.repeat_override_reason`. Without it the Idea Gate returns `REPEAT_FAILED`.

Key constraint: if the directive is currently in `completed/` with state PORTFOLIO_COMPLETE, `reset_directive.py` is required before the pipeline will re-admit it. State is keyed by the directive filename stem — PORTFOLIO_COMPLETE blocks re-admission even if the file is in INBOX.

```bash
# Reset before placing in INBOX
python tools/reset_directive.py <STRATEGY_ID> --reason "<why>"
# If state is IDLE (no state file), reset is not needed — proceed directly to run.
```

---

## Rerun Lifecycle (Manual — When `rerun_backtest.py` Is Not Used)

The safe manual sequence for ENGINE or DATA_FRESH reruns:

```
1. EDIT directive (completed/)
   - Add test.repeat_override_reason (≥50 chars, machine-scannable prefix)
   - Update test.end_date to latest available
   - For ENGINE: no other changes needed
   - For SIGNAL: also bump signal_version and remove ENGINE_OWNED indicators

2. RESET directive state (if PORTFOLIO_COMPLETE)
   python tools/reset_directive.py <ID> --reason "<why>"

3. COPY to INBOX
   cp backtest_directives/completed/<ID>.txt backtest_directives/INBOX/

4. TOUCH approved marker (if strategy.py was modified)
   touch strategies/<ID>/strategy.py.approved

5. UPDATE sweep registry (if directive hash changed due to indicator removal)
   Use _write_yaml_atomic directly — do NOT use new_pass.py --rehash for
   patches that already exist (it creates duplicate YAML keys).

6. RUN pipeline
   python tools/run_pipeline.py <STRATEGY_ID>
   - First run may pause at EXPERIMENT_DISCIPLINE if provisioner patches strategy.py
   - If so: touch approved again, then run again (second run bypasses via baseline age)

7. FINALIZE
   - Mark old run_id as superseded in master_filter (is_current=0)
   - Set is_current=1 on new run_id
   - Or use: python tools/rerun_backtest.py finalize --old-run-id <old> --new-run-id <new> --reason "<why>"
```

---

## Stage-3 Non-Idempotency

**Stage-3 (`stage3_compiler.py`) does NOT update existing rows** — it only appends new rows. If the old run's row for `<strategy>_<symbol>` already exists in `Strategy_Master_Filter.xlsx` and `ledger.db`, Stage-3 will skip the new run (cardinality gate returns "already written").

**Before re-running any directive that previously reached Stage-3:**

1. Remove old rows from `Strategy_Master_Filter.xlsx` (the `<strategy>_<symbol>` rows)
2. Confirm via `ledger.db`: `SELECT COUNT(*) FROM master_filter WHERE strategy LIKE '<ID>%'`
3. Delete stale rows or use `reset_directive.py --to-stage4` for large multi-symbol sets

Skipping this step causes Stage-3 to silently no-op — the pipeline reports "0 rows added" and uses the old (pre-rerun) metrics throughout Stages 4-5.

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
| `/execute-directives`            | Dispatch the prepared INBOX directive through pipeline |
| `/state-lifecycle-cleanup`       | Quarterly archival of superseded rows to parquet       |
| `/promote`                       | Promote the new run_id to BURN_IN after verification   |

---

## Related Files

| File                           | Location                                         |
|--------------------------------|--------------------------------------------------|
| Rerun tool                     | `tools/rerun_backtest.py`                        |
| Ledger DB + mark_superseded    | `tools/ledger_db.py`                             |
| Idea Gate (Stage -0.20)        | `tools/orchestration/admission_controller.py`   |
| Classifier Gate (Stage -0.21)  | `tools/classifier_gate.py`                      |
| Directive signature schema     | `tools/directive_schema.py`                     |
| Audit log                      | `outputs/logs/rerun_audit.jsonl`                 |
| Overrides audit (Idea Gate)    | `governance/idea_gate_overrides.csv`             |

---

## Rerun Contract (LOCKED — 2026-04-17)

- **Same-stem baseline enforced** — classifier requires same directive filename; `repeat_override_reason` is the only Idea-Gate bypass.
- **Stage-3 non-idempotent** — compiler appends by `run_id`; old rows must be removed before rerun or Stage-3 silently no-ops.
- **Stage-4 supersedence required** — old `run_id` must be marked `is_current=0` via `finalize`; no row deletion, no auto-overwrite.
- **Directive = execution window** — `start_date`/`end_date` in the directive are the authority; no silent clamping by the engine.

---

## System Contract

- `master_filter` is append-only. Reruns never delete — they supersede via `is_current=0`.
- `is_current=1 AND quarantined=0` is the canonical filter for "live, eligible-for-promotion" rows. `filter_strategies.py` enforces this.
- `test.repeat_override_reason` is the ONLY sanctioned Idea-Gate bypass. The tool's auto-prefix is machine-parseable for forensic reconstruction.
- `signal_version` increments are the ONLY sanctioned way to satisfy the Classifier Gate's SIGNAL-diff rule. Never hand-edit it outside this tool.
- Every `prepare` and `finalize` invocation is written to `outputs/logs/rerun_audit.jsonl` — do not bypass the tool with manual YAML edits.
