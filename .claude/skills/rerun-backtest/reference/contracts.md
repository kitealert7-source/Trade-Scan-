# Rerun contracts — LOCKED Rerun Contract + System Contract

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

## Rerun Contract (LOCKED — 2026-04-17, amended 2026-05-24, 2026-06-12, 2026-06-14)

- **Variant-rotated reruns** — every rerun gets a fresh `__E###` suffix on filename + `test.name`. `test.strategy` stays at the base stem. `repeat_override_reason` is still the only Idea-Gate bypass.
- **Stage-3 idempotent by `run_id`** *(amended 2026-06-12)* — the compiler skips a *repeated* `run_id`, never a new one; a rerun's new `run_id` writes normally. A collision with a prior `is_current=1` row for the same `(strategy,symbol)` is resolved **at the writer** (Phase-0): auto-supersede for declared reruns, fail-loud otherwise. **No manual row removal** (the prior "remove old rows first" rule is retired).
- **Supersedence is enforced, not optional** *(amended 2026-06-12)* — for a **declared** rerun the prior `run_id` is auto-marked `is_current=0` at Stage-3 (Phase-0, `570f6c48`); `finalize` remains the path for `--quarantine` (BUG_FIX) and as the explicit/fallback. Append-only: flag `is_current=0`, never delete; no auto-overwrite of row identity or metrics.
- **Directive = execution window** — `start_date`/`end_date` in the directive are the authority; no silent clamping by the engine.
- **signal_version lives in test:** — `signal_version` is a child of the `test:` block per `canonical_schema.ALLOWED_NESTED_KEYS["test"]`. Root-level writes collide at the test→root mirror in `pipeline_utils.parse_directive_with_canonical_test` and are also rejected by Stage -0.25 canonicalization. The tool defensively strips any stray root-level key.
- **Cross-skill contract with `/hypothesis-testing`** *(added 2026-06-14)* — the category taxonomy (`DATA_FRESH`/`SIGNAL`/`ENGINE`/`PARAMETER`/`BUG_FIX`) and the supersede-vs-compare boundary are **shared** with the [`/hypothesis-testing`](../../hypothesis-testing/SKILL.md) §1.0 divert table, which routes reruns based on them. If either changes here, **review and update `/hypothesis-testing` §1.0 in the same change** — a one-sided edit silently drifts the two skills apart. (Reciprocal of the ownership note in `/hypothesis-testing` §0.)
- **Retirement is part of the rerun** *(added 2026-06-14)* — a rerun is **not complete until its predecessor is retired**: its row archived to `TradeScan_State/retired/retired_runs.parquet` and its heavy artifacts pruned, via [`/pipeline-state-cleanup`](../../pipeline-state-cleanup/SKILL.md)'s authorized drop (archive-BEFORE-drop; the only sanctioned ledger-row removal under Invariant #2). Applies to **all** rerun categories. The predecessor's seed (directive + `RECYCLE_RULE_SOURCE.py`) is retired only *after* its rerun consumes it. Keeps the live ledger trim; the cold archive is the don't-re-test record. Enforcement = the `retire` tool step + the `/session-close` drift check (pending).

## System Contract

- `master_filter` is append-only. Reruns never delete — they supersede via `is_current=0` (auto at Stage-3 for **declared** reruns since Phase-0 `570f6c48`; via `finalize` otherwise / for `--quarantine`).
- `is_current=1 AND quarantined=0` is the canonical filter for "live, eligible-for-promotion" rows. `filter_strategies.py` enforces this.
- `test.repeat_override_reason` is the ONLY sanctioned Idea-Gate bypass. The tool's auto-prefix is machine-parseable for forensic reconstruction.
- `signal_version` increments are the ONLY sanctioned way to satisfy the Classifier Gate's SIGNAL-diff rule. Never hand-edit it outside this tool.
- Every `prepare` and `finalize` invocation is written to `outputs/logs/rerun_audit.jsonl` — do not bypass the tool with manual YAML edits.
