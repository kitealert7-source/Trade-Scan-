# Cointegration Screener — v2 Eligibility Backfill (BC1)

**Date:** 2026-05-30
**Status:** Design — pending operator ack before BC2 lands
**Scope:** `tools/cointegration_backfill_screener.py` extension + supervised execution
**Predecessor:** `COINTEGRATION_SCREEN_MATH_V2.md` (C1-C4 — math fix landed)
**Operator decisions locked this turn:**
  - Backfill range: **2024-01-01 → present** (calendar boundary, not per-pair)
  - **Overwrite** v1 screener history (no PK migration)
  - Reuse existing backup tables (`<table>_backup_<UTC_TIMESTAMP>`) for rollback
  - Extend tool for: 1d + 4h, parallel compute, resumable execution, chronological upsert preserved for hysteresis correctness

---

## 1. Why this exists

C1-C4 landed the math correction in code. The screener's *historical* eligibility series is still v1: every row in `cointegration_daily` and `singles_daily` was written under raw-price ADF with unit-root critical values. Any strategy backtest over 2024+ that consumes the screener's regime / hedge_ratio / current_zscore inputs reads v1 features — even though the code itself has been v2 since commit `7154d6e`.

Without backfill, "how would log+EG have qualified pairs over the last 2 years" is unanswerable, and any new backtest with new strategy parameters (e.g., the z=1.5 / exit-at-0 variants the operator named) inherits v1 eligibility decisions silently.

This document is the plan to rebuild the *authoritative v2 eligibility series for 2024-01-01 onward*. It does not rebuild the episode corpus and does not re-run any past backtest.

---

## 2. What changes / what doesn't

| Aspect | After backfill |
|---|---|
| `cointegration_daily` rows for as_of ≥ 2024-01-01 | **v2_log_eg** (overwriting v1_raw_adf at the same PK) |
| `singles_daily` rows for as_of ≥ 2024-01-01 | **v2_log_adf** (overwriting v1_raw_adf) |
| `cointegration_triggers` | Truncated then rebuilt from the full v2 history via `rebuild_triggers_from_history` |
| Pre-2024-01-01 rows in live tables | **REMOVED from live**; preserved in `<table>_backup_<suffix>` for rollback only |
| `cointegration.db` PRIMARY KEY | UNCHANGED — relying on `INSERT OR REPLACE` semantics |
| `cointegration_sheet` (episode corpus, 339 rows) | UNCHANGED — different table, different DB; v1-tagged rows stay frozen |
| Per-backtest `results_basket_per_bar.parquet` files | UNCHANGED — frozen on disk, integrity-signed via `parquet_sha256` |
| Strategy code, gates, basket loader | UNCHANGED — they consume whatever's in the table; no methodology filter |
| `MPS Cointegration` tab | After re-export: 339 rows still showing methodology=`v1_raw_adf` (corpus side unchanged) |
| Screener `Cointegration_Screener.xlsx` | After re-export: surfaces v2-only data for as_of ≥ 2024-01-01 |

**Pre-2024 design choice (default in BC2):** the existing `_truncate_tables` is a wholesale `DELETE FROM cointegration_daily`. Reusing it wipes the entire live table, and the backup preserves the pre-2024 v1 history. Live tables therefore represent **one consistent methodology (v2) over one coherent date range (2024+)** with no methodological discontinuity inside the live data. Operators that need pre-2024 history can restore the backup. The alternative — `DELETE WHERE as_of >= '2024-01-01'` — would preserve pre-2024 v1 in live tables, but mix v1 and v2 features across the 2023-2024 boundary in any strategy that reads hedge_ratio or adf_pvalue across that join. **Recommend the wholesale-truncate path** to avoid that discontinuity. If you'd rather preserve pre-2024 v1 in live, flag now and BC2 will scope the truncate accordingly.

---

## 3. The reproducibility cost (explicit, named)

After backfill, any future re-run of a 2024+ pair-based directive will read v2 features instead of v1. Concrete consequences:

- `hedge_ratio` flips from raw-OLS β (often 0.1–10) to log-space β (typically ≈1.0). `cointegration_meanrev_v1_2`'s β-weighted lot sizing changes materially.
- `adf_pvalue` becomes EG/MacKinnon (stricter). Fewer regime=cointegrated days, fewer trigger rows, fewer trades for `pine_ratio_zrev_v1`.
- `regime` flips where v1 said "cointegrated" but v2 says "broken". The `window_validity_gate` may reject directives it previously admitted.

**What is NOT broken:**
- The 339 stored episode results in `cointegration_sheet` — the per-bar parquet is frozen, the `canonical_*` metrics are stored, `parquet_sha256` is sealed. Re-enrichment (`reenrich_cointegration_row`) reads the parquet, not the screener DB.
- Excel views render whatever's in the tables; the 339 corpus rows keep their `v1_raw_adf` tag.

The operator has explicitly accepted this tradeoff in choosing overwrite over PK extension.

---

## 4. Trigger regeneration (verified pre-BC1)

`tools/cointegration_db.py:587-608 rebuild_triggers_from_history`:
1. `DELETE FROM cointegration_triggers`
2. `SELECT … FROM cointegration_daily WHERE regime='cointegrated' AND ABS(current_zscore) >= TRIGGER_Z_FLOOR`
3. Calls `_upsert_triggers_from_rows` over the result set.

The per-as-of upsert path (`_upsert_triggers_from_rows`, called from `upsert_from_parquet`) and the bulk rebuild **share the same implementation**. Codebase grep confirms no other trigger-write paths exist outside these two functions. The backfill script calls the bulk rebuild at the end (line 156), so triggers are authoritatively re-derived from the full v2 daily history regardless of the per-as-of trigger writes that happen during the loop.

Going forward, the daily runner's Phase 2 (`cointegration_db.main(['--upsert'])`) writes daily rows + per-as-of triggers via the same shared function — so post-backfill consistency is maintained automatically.

---

## 5. Backfill range — chosen, not derived

Operator-locked: **2024-01-01 → present**, a calendar boundary.

The memory hint `feedback_test_window_must_match_signal_class.md` recommends per-pair window matching for *strategy tests*. The eligibility series being backfilled here is the substrate strategies consume; the 2024-01-01 boundary defines its supported date range, not a strategy's test window. Operator has confirmed the distinction holds and selected the calendar boundary; per-pair adaptive windows for the eligibility series are explicitly out of scope.

---

## 6. Tool extension scope (BC2 — code commit)

### 6.1 Argparse additions to `cointegration_backfill_screener.py`

| Flag | Behavior | Default |
|---|---|---|
| `--tfs 1d,4h` | Comma-separated list of TFs; validated against `SUPPORTED_TFS` | `1d,4h` |
| `--max-parallel N` | Worker count for compute phase; bounded by `min(N, cpu_count - 2)` to leave cores for the parent | `1` (serial, preserves existing behavior when no flag set) |
| `--resume` | Skip truncate + backup; resume from `max(as_of) WHERE methodology_version IN ('v2_log_eg','v2_log_adf')` per TF | off |
| `--workdir PATH` | Override the temp-parquet directory (default: `tmp/backfill_<UTC_TIMESTAMP>/`) | auto |

Existing flags (`--years`, `--start`, `--end`, `--dry-run`, `--skip-backup`) preserved.

### 6.2 Compute parallelism — pure compute, isolated output

Uses `concurrent.futures.ProcessPoolExecutor`. Each task is one `(as_of, tf)` pair:

1. Worker loads closes for the TF's full universe (cached per-process via existing `_load_native_closes`).
2. Worker calls `run(as_of=as_of, tf=tf)` — produces a DataFrame of all `(pair, lookback)` rows for that as_of × tf.
3. Worker calls `run_singles(as_of=as_of, tf=tf, synthetic_specs=[("BTCUSD","ETHUSD")])`.
4. Worker writes both DataFrames to per-(as_of, tf) parquet files in `--workdir`:
   - `coint_<tf>_<as_of>.parquet`
   - `singles_<tf>_<as_of>.parquet`
5. Worker returns the file paths; no DB access from workers.

Validated pattern: `feedback_parallelization_selectivity.md` — pure-compute → isolated-output, third validated pattern from registry topology (`--max-parallel 8`).

### 6.3 Serial chronological upsert (hysteresis correctness)

After all workers complete, the parent walks the temp parquets in **strict chronological order**:

```
for as_of in sorted(dates):
    for tf in tfs:
        upsert_from_parquet(conn, workdir / f"coint_{tf}_{as_of}.parquet")
        upsert_singles_from_parquet(conn, workdir / f"singles_{tf}_{as_of}.parquet")
```

`upsert_from_parquet` calls `query_for_classifier(methodology_version=...)` which now (post-C3) filters by methodology — so the hysteresis classifier sees only same-cohort priors. The C3 regime-reset bootstrap kicks in for the first ≥5 as_ofs per pair-window, then hysteresis engages naturally as v2 history accumulates.

Upsert wall-clock cost: ≈50 ms per `(as_of, tf)` call × 440 as_ofs × 2 TFs = ~44 seconds total. Negligible vs compute.

### 6.4 Resume semantics

On `--resume`:
1. Skip `_backup_tables` (warn if no prior backup exists; refuse if `--skip-backup` was used in the original run).
2. Skip `_truncate_tables` entirely.
3. Per TF, query `max(as_of) FROM cointegration_daily WHERE methodology_version IN ('v2_log_eg','v2_log_adf') AND tf=?` — call this `resume_after`.
4. Recompute the date range as `bdate_range(max(resume_after + 1 bdate, start_date), end_date)`.
5. Proceed normally — compute phase enqueues only missing (as_of, tf) pairs; upsert phase walks chronologically.

This is naturally idempotent: re-running `--resume` after a clean completion is a no-op (the resume_after equals the end_date).

### 6.5 Truncate semantics

Default: existing wholesale `DELETE FROM …` for cointegration_daily + singles_daily + cointegration_triggers (preserves backup → live becomes pure v2 from 2024-01-01).

Alternative (if operator pushes back on §2): `DELETE FROM … WHERE as_of >= ?` parameterized by `start_date`. BC2 will land the wholesale path by default and leave a one-line code change as the alternative — not adding a flag for it unless requested.

### 6.6 What stays as-is

- `_backup_tables` mechanism: unchanged. Suffix is the UTC timestamp at start of run.
- `rebuild_triggers_from_history` call at the end of the loop: unchanged.
- Final-state summary log lines: unchanged.

### 6.7 Mandatory pre-flight: scheduled-writer pause check

BC2 ships a hard pre-flight that the tool runs **before** the backup step, **before** the truncate, and **before** the compute loop. The check refuses to start the backfill if the production `cointegration_daily_runner` scheduled task is enabled — operator discipline is not sufficient given the concurrent-write blast radius (a daily-runner tick mid-backfill would write a v1-styled row from the still-deployed but soon-truncated baseline + race against the chronological upsert).

**Implementation:** Windows Task Scheduler query via `schtasks /Query /TN AntiGravity_Daily_Preflight /V /FO LIST`. This is the DATA_INGRESS daily preflight task (`DATA_INGRESS/engines/ops/invoke_preflight.ps1`), which on RUN_DAILY triggers `invoke_daily_pipeline.ps1` — the daily pipeline in turn invokes `Trade_Scan/tools/cointegration_daily_runner.py` as a downstream consumer (`invoke_daily_pipeline.ps1` §"COINTEGRATION SCREENER" line ~300-334). Parse the `Scheduled Task State` field; refuse if not `Disabled`. The legacy `CointegrationScreener_DailyRun` task (registered by `outputs/cointegration_screener_v1/phase4/register_daily_task.ps1`) is superseded by this DATA_INGRESS path and is typically not registered — checking only the legacy name would silently pass while the real trigger remained armed (BC2 errata 2026-05-30). If the task is unregistered (query returns non-zero exit), pass with an info log line (no scheduled writer to pause).

**Failure behavior:** The tool prints a fatal error naming the task and the exact disable command (`schtasks /Change /TN AntiGravity_Daily_Preflight /DISABLE`) and exits non-zero before any DB connection opens. **No bypass flag.** If a future operator needs to bypass for a one-off, they can edit the source — the friction is deliberate per the operator's "mandatory" instruction (2026-05-30).

**Re-enable after BC4:** the post-BC4 verify step in §8 reminds the operator to re-enable via `schtasks /Change /TN AntiGravity_Daily_Preflight /ENABLE` once the v2 history is validated.

---

## 7. Compute envelope (from BC1 probe data, 5 dates spread across 2024-2025)

Per-(as_of, tf) measured timings (single-window calls; production backfill batches both windows per `run()` call and amortizes data load):

| Config | Mean | Max |
|---|---|---|
| 1d × 252 | 3.86 s | 4.22 s |
| 1d × 504 | 5.26 s | 5.84 s |
| 4h × 1500 | 21.72 s | 24.17 s |
| 4h × 3000 | 46.49 s | 52.03 s |

With both windows batched per `run()` call (single data load), estimated per-as_of:
- 1d (252 + 504): ≈6 s
- 4h (1500 + 3000): ≈55 s

Backfill range ≈ 440 business days.

| Mode | 1d total | 4h total | Wall clock |
|---|---|---|---|
| Serial | 44 min | 403 min (≈6.7 h) | **~7.5 h** |
| Parallel-8 (compute) + serial upsert | ~5.5 min | ~50 min | **~1 h** |

The DB upsert serial step adds ~44 s end-to-end (440 × 2 TFs × ~50 ms). Negligible vs compute. The final `rebuild_triggers_from_history` call adds a few seconds — also negligible.

Recommended `--max-parallel 8` (registry topology was validated at this level per `feedback_parallelization_selectivity`).

---

## 8. Atomic commits + operational phases

### BC2 — Tool extension (one commit)

- File: `tools/cointegration_backfill_screener.py` extended per §6 (flags, parallel compute, chronological upsert, resume)
- Tests:
  - `test_backfill_parses_tf_list` — `--tfs 1d,4h,1h` rejected; `1d,4h` accepted
  - `test_backfill_max_parallel_bounded` — N > cpu_count clamped
  - `test_backfill_workers_produce_isolated_parquets` — synthetic small range; verify N parquets written, content matches direct `run()` call
  - `test_backfill_upsert_order_is_chronological` — synthetic 3-day range, mock upsert_from_parquet to capture call order, assert ASC by as_of
  - `test_backfill_resume_from_max_as_of` — seed live table with 3 v2 rows, run with `--resume`, assert only as_ofs > max are queued
  - `test_backfill_methodology_tag_propagation` — confirm written rows carry the post-C3 tags from `cointegration_screen.METHODOLOGY_VERSION` (no hardcoding in the tool)
- Pre-commit: must pass the existing 70-gate suite. Regression harness should not trigger (no capital/portfolio/promote touched).

### BC3 — Small-slice operational dry run (no commit)

- 5 trading days, e.g., `2024-01-15 → 2024-01-19`, `--max-parallel 4`, `--tfs 1d,4h`
- Verify:
  - Workdir contains 5 × 2 = 10 daily parquets + 10 singles parquets
  - cointegration_daily has 5 days × 2 TFs × 2 windows × 465 pairs = **9,300 v2 rows** for that slice (plus backup table for pre-existing v1)
  - singles_daily has 5 days × 2 TFs × 2 windows × (universe + 1 synthetic) rows tagged `v2_log_adf`
  - cointegration_triggers populated by the bulk rebuild
  - methodology distribution: 100 % v2 in live tables, v1 fully in backup
  - Spot-check 3 pairs against the C3 universe diagnostic (run the same as_of through `run()` directly, compare adf_pvalue byte-for-byte)
- Resume test: kill the loop at day 3 of 5, restart with `--resume`, verify only days 4-5 are processed and final state matches the unkilled run.

### BC4 — Full execute (no commit; logged supervised run)

- Full range `2024-01-01 → present`, `--max-parallel 8`, `--tfs 1d,4h`
- Estimated wall clock: ~1 hour
- Pre-flight: BC2 §6.7 mandatory scheduler check enforces the pause (refuses to run otherwise — no operator override). Operator additionally confirms backup tables created and `cointegration.db` has free space (~few hundred MB).
- Post-verify also re-enables the daily runner: `schtasks /Change /TN AntiGravity_Daily_Preflight /ENABLE`.
- Mid-flight: progress log every 25 iterations (existing behavior).
- Post-verify:
  - Row counts per (tf, lookback) — for 1d: 440 as_ofs × 2 lookbacks × 465 pairs ≈ 409,200 rows.
  - methodology distribution: live = 100 % v2; backup = 100 % v1 (the pre-2024 v1 carries forward in backup only).
  - Universe diagnostic: re-run the C3 sanity check via `tools/cointegration_excel.py --export` and confirm the Summary tab's regime distribution is plausible (qualified pair count in low double-digits for 1d × 252 — matches the C3 audit-of-audit at 83 ± noise).
  - `cointegration_triggers` non-empty; spot-check the most recent day has the same triggers as a re-run via the daily runner.

After BC4 completes, the next `cointegration_daily_runner.py` tick will append one new v2 row per (pair, tf, lookback) consistent with the backfilled history. No further action needed; the daily runner does not require any update.

---

## 9. Break-test plan (executed inside BC2's test suite + BC3's small slice)

1. Per-(as_of, tf) parquet exists for every requested combination; worker failures surface in the parent's exception aggregator (not silent).
2. Chronological upsert applied without race; no duplicate-PK errors.
3. Hysteresis classifier engages as priors accumulate: history_depth=0 on as_of #1, increments through #5, then full hysteresis from #6.
4. `rebuild_triggers_from_history` produces a count equal to sum of per-as_of trigger writes (consistency invariant).
5. Backup tables created with non-zero row counts (pre-existing v1 preserved).
6. `--resume` from mid-slice picks up exactly where it left off; final state byte-equivalent to unkilled run.
7. `--max-parallel 1` (serial) produces byte-identical DB state as `--max-parallel 8` (parallel) — determinism guard (modulo `inserted_at` timestamps).

---

## 10. Out of scope

- Pre-2024 backfill (operator: no full-history)
- PK extension (operator: overwrite, accept reproducibility cost)
- `cointegration_sheet` rebuild (operator: 339 episodes stay v1-tagged; corpus is not re-screened or re-backtested)
- FDR (deferred since C1 design doc §6)
- Per-pair adaptive backfill windows (memory hint flagged; operator chose calendar boundary)
- Wider singles backfill beyond the existing single hardcoded `("BTCUSD","ETHUSD")` synthetic
- Changes to the daily runner (`cointegration_daily_runner.py`)
- Changes to strategy code in `recycle_rules/`

---

## 11. Rollback path

1. Stop any in-flight processes touching `cointegration.db`.
2. Take a snapshot of the current (post-backfill) DB for forensic comparison: `cp cointegration.db cointegration.db.postBC4`.
3. In SQLite shell:
   ```sql
   BEGIN;
   DELETE FROM cointegration_daily;
   INSERT INTO cointegration_daily SELECT * FROM cointegration_daily_backup_<suffix>;
   DELETE FROM singles_daily;
   INSERT INTO singles_daily SELECT * FROM singles_daily_backup_<suffix>;
   DELETE FROM cointegration_triggers;
   INSERT INTO cointegration_triggers SELECT * FROM cointegration_triggers_backup_<suffix>;
   COMMIT;
   ```
4. Verify row counts match pre-backfill snapshot.

The backup tables persist after the backfill; operator can drop them via `DROP TABLE …_backup_<suffix>` once confident the v2 history is sound (recommended: keep for at least one week of operational runs).

---

## 12. Open follow-up after BC4 completes (NOT in scope for this design)

The provisional conclusions in `project_cointegration_methodology_audit.md` (auto-memory) — "cointegration-as-1d×252-screen is weak", "strength anti-correlates with edge", etc. — were derived from the v1-tagged 339-episode corpus. With the v2 eligibility series now available, the operator can in principle:
- Run the same Spearman analyses against the v2 eligibility history to see whether the v1-corpus findings hold under the corrected math.
- Or author new directives that exploit specific v2-cointegrated spans.

Neither is in BC4 scope; both are independent future decisions.
