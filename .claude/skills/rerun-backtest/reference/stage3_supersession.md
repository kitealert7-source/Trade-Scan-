# Stage-3 idempotency + Phase-0 supersession

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

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
