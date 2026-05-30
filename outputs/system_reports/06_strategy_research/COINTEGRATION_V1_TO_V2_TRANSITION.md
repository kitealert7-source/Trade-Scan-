# COINTEGRATION CORPUS — v1 → v2 TRANSITION SNAPSHOT

**Date:** 2026-05-30
**Author:** session (operator-driven cleanup per CLAUDE.md Invariant #2)
**Scope:** retirement of the `v1_raw_adf` cointegration corpus before v2 backtest execution

---

## 1. Why this snapshot exists

v1 results were produced under three sources of error that are now corrected:

| Layer | v1 (retired) | v2 (live) |
|---|---|---|
| Cointegration test | raw-price ADF on the spread | log-price Engle-Granger, MacKinnon (1996) criticals |
| Regime classifier | single-day `pvalue<0.05` flip | 5-day hysteresis (LOOKBACK=5, MIN_COINT_COUNT=4) |
| Eligibility windowing | retrospective `MIN_DAYS=30` (look-ahead) | causal confirmation `N=5` (entry = onset+6, exit = break+1) |

The v1 ledger rows, the v1 backtest folders on disk, and the v1 directive files in `completed/` are therefore no longer interpretable as valid edge evidence — they reflect a math + filtering procedure we have explicitly disowned. They are being deleted, not archived in the working set, because they will not be re-read for analysis.

This snapshot is the durable record of what was retired and how the v1 → v2 transition was framed.

---

## 2. Snapshot block

```
v1 corpus (retired this session):
  episodes            = 339   # rows in cointegration_sheet with real YYMMDD E-stamps
  + dev/test rows     = 59    # __E001 (26) + __E003 (22) + __E004 (4) + __E005 (7)
  total ledger rows   = 398   # all rows tagged methodology_version='v1_raw_adf'
  current (live)      = 330
  superseded          = 68
  on-disk folders     = 330   # TradeScan_State/backtests/<directive_id>_<basket>
  completed/ files    = 366   # backtest_directives/completed/*.txt v1 directives
  unique pair_a/pair_b = 241

v2 corpus (REGENERATED 2026-05-30 after CR-EXIT-FIX, see §4.5):
  episodes            = 488
  baskets (pairs)     = 252 (approx; recount on first successful run)
  staging dir         = backtest_directives/cointrev_v3_staging/

Generation rules (v2 — final):
  N                       = 5
  entry_idx               = onset_idx + N + 1     # = onset + 6
  exit_idx                = last_coint_idx        # last cointegrated bar of span
  span qualifies iff      entry_idx <= last_coint_idx (ncoint >= N + 2)
  cointegration test      = log-price Engle-Granger, MacKinnon criticals
  classifier              = hysteresis (LOOKBACK=5, MIN_COINT_COUNT=4)
  methodology_version     = v2_log_eg
```

**Superseded rule (do not relitigate):**
The first 2026-05-30 corpus used `exit_idx = break_idx + 1` (one trading day past the regime break, encoding the "exit on day after break is observed" execution rule). All 527 directives failed `window_validity_gate` because the window extended 1-2 bars past `last_coint_date`. Operator decision (2026-05-30): the directive window expresses the **regime period**, not the execution day. The "exit on break+1" rule is reserved for a future strategy-side experiment, implemented in engine exit logic, not in corpus construction. See §4.5.

Indexing convention (locked at the generator):
```
onset day        = day 0  (first cointegrated business day under hysteresis)
confirmation     = next N completed business days (no look-ahead)
entry eligibility = following business day
break day        = first non-cointegrated day after onset (or open at end)
exit eligibility = day after break (open span → series[-1])
```

---

## 3. Pre-cleanup state — captured 2026-05-30

### 3.1 cointegration_sheet (ledger)

| methodology_version | row count |
|---|---:|
| v1_raw_adf | 398 |
| (no v2 rows yet) | 0 |

is_current breakdown of v1 rows: 330 live, 68 already superseded.

### 3.2 BC4 screener backups (kept untouched)

| Table | Rows |
|---|---:|
| `cointegration_daily_backup_20260530T051931Z` | 1,127,663 |
| `cointegration_daily_backup_20260530T053410Z` | 1,127,663 |
| `cointegration_daily_backup_20260530T054600Z` | 1,127,663 |
| `cointegration_daily_backup_20260530T055216Z` | 8,695 |
| `cointegration_triggers_backup_20260530T*` | 25,539 × 3 + 89 |
| `singles_daily_backup_20260530T*` | 77,598 × 3 + 600 |

These are NOT part of the cleanup. They remain in `cointegration.db` until operator authorizes their removal.

### 3.3 Disk

- 330 `COINTREV_V3` backtest folders under `TradeScan_State/backtests/` (matched to v1 directive_ids)
- 25 raw-only orphan folders (8 are `COINTREV_V3` v1 strays; 17 are unrelated ad-hoc tests in RSIAVG / FAKEBREAK / PSBRK families)
- 366 v1-era `.txt` directives in `backtest_directives/completed/`
- 527 v2 staging directives in `backtest_directives/cointrev_v3_staging/`

---

## 4. Post-cleanup state — captured 2026-05-30

### 4.1 cointegration_sheet (ledger)

| methodology_version | is_current | count | delta |
|---|---:|---:|---:|
| v1_raw_adf | 1 (live) | 0 | -330 (dropped via `repair_integrity --action drop --execute`) |
| v1_raw_adf | 0 (superseded) | 68 | unchanged — tombstones from prior supersession events, retained as audit lineage |
| v2_log_eg | — | 0 | none yet — populated when the staged v2 corpus runs |

**Residual 68 superseded v1 rows:** these were already `is_current=0` before this session (their disk folders had been removed at supersession time, pre-this-session). They live outside the `repair_integrity` scanner's scope, which only inspects `is_current=1`. They are inert tombstones — they cannot influence any deployment, screening, or rendering decision. Retained rather than DELETEd because they preserve a minimal audit trail of the v1 → v1 supersession events that occurred during the original v1 corpus build.

### 4.2 Disk

| Path | Before | After |
|---|---:|---:|
| `TradeScan_State/backtests/*COINTREV_V3*/` | 330 | 0 |
| `TradeScan_State/runs/<v1_run_id>/` | 323 of 330 present | 0 |
| Raw-only orphan folders (any family) | 18 (after v1 sweep) | 0 |
| `backtest_directives/completed/` | 366 | 0 |
| `backtest_directives/archive/v1_legacy_corpus/` | (new) | 366 |
| `backtest_directives/cointrev_v3_staging/` | 527 | 527 (untouched) |

### 4.3 BC4 screener backups — UNCHANGED

All 12 backup tables in `cointegration.db` preserved with original row counts. None touched by this cleanup.

### 4.4 MPS::Baskets cleanup (side-effect)

`repair_integrity` also detected 39 orphan rows in MPS::Baskets (older `COINTREV_V1` / `COINTREV_V2` / `COINTREV_V3_L100__E002`-style dev runs whose disk artifacts were already gone). 20 were dropped; the remaining 19 carry `quarantine_status` lineage tags (SUPERSEDED / ARCHIVED_UNRESOLVED) and are protected from auto-drop by design. No action needed.

### 4.5 CR-EXIT-FIX — exit-rule revision (2026-05-30, after first corpus rejection)

**Problem.** The first v2 corpus (527 directives) was generated with `exit_idx = break_idx + 1` (one trading day past the regime break, encoding the operator's "exit on day after break is observed" rule from this session). When promoted to INBOX and run, **every directive failed the `window_validity_gate`** at admission with messages of the form:

```
test window [<start> → <end>] is not inside a continuous cointegrated regime:
window ends <end> — after the aligned span closes (<last_coint_date>);
regime left 'cointegrated' after that
```

The window's `end_date` landed 1–2 bars **past** the cointegrated span's `last_coint_date`, which the gate (operator-locked 2026-05-28) does not admit without `methodology_override`.

**Resolution.** Two operator-locked rules were in conflict; the operator chose to keep the gate unchanged and revise the generator:

```python
# tools/generate_cointrev_v3_directives.py — spans_confirmation_safe
exit_idx = last_coint_idx   # was: break_idx + 1
# Qualification tightens accordingly:
span qualifies iff entry_idx <= last_coint_idx   # equivalent to ncoint >= N + 2
```

The "exit on day after break" rule is now reserved for a **future strategy-side experiment** — implemented inside the engine's exit logic (which has live access to the regime feed), not in the corpus's directive windows. The backtest window represents the regime period; the live exit fires on `break_idx + 1` via the engine if the strategy elects that exit rule.

**Effect on corpus size.** Spans of length `ncoint == N + 1 == 6` (which previously qualified with a 1-bar tradable window where entry and exit both landed in the breaking regime) now drop out — entry_idx would land at `last_coint_idx + 1`, which is the first non-cointegrated bar. The corpus shrinks from **527 → 488 episodes** (-7.4%).

**Verification.** All 488 directives pass `window_validity_gate.evaluate_window_validity()` with status=PASS. Spot-check (earliest/median/latest):

| Sample | start_date | end_date | gate.span_start | gate.span_end | continuous_obs |
|---|---|---|---|---|---|
| AUDJPYAUDNZD __E240109 (earliest) | 2024-01-09 | 2024-02-20 | 2023-12-29 | 2024-02-20 | 37 |
| ESP35USDCHF __E260519 (median) | 2026-05-19 | 2026-05-29 | 2026-05-11 | 2026-05-29 | 15 |
| USDJPYXAUUSD __E260324 (latest) | 2026-03-24 | 2026-04-21 | 2026-03-16 | 2026-04-21 | 26 |

**Pipeline run result (T+~17min, --max-parallel 8):**

| Metric | Value |
|---|---:|
| Directives processed | 488 |
| Ledger rows landed (`v2_log_eg`, `is_current=1`) | 473 |
| Distinct pairs | 258 |
| Net pct — mean / median | +0.15% / +0.12% |
| Net pct — min / max | -59.41% / +54.20% |
| Max DD pct — mean / median | 6.95% / 3.60% |
| Trades — mean / median | 65 / 32 |
| Zero-trade rows (very short windows) | 27 / 473 (5.7%) |
| Profitable rows | 246 / 473 (52.0%) |

Post-run Excel surfaces (`Master_Portfolio_Sheet.xlsx`, `Filtered_Strategies_Passed.xlsx`) re-formatted by the batch tail. The Cointegration tab now reflects the v2_log_eg cohort exclusively (v1_raw_adf rows were dropped from the ledger pre-run, see §4.1).

**488 → 473 delta — audit (operator request 2026-05-30):**

All 15 missing rows are admission-rejections at the pipeline's stage-0.5 / stage-1 minimum-bars gate. No backtest folder was created for any of them; no engine invocation occurred. Window-duration distribution:

| Window | Count | Pattern |
|---|---:|---|
| 0 calendar days (start == end) | 11 | Open spans where `entry_idx == last_coint_idx` (8 land on 2026-05-29, the series-end day) |
| 1 calendar day | 3 | Just-at-threshold spans (`ncoint == N+2 == 7`) with a weekend in the confirmation period |
| 3 calendar days (≈1 business day) | 1 | `NAS100US30 __E251128` — Friday→Monday |

Root cause is structural: the 15M strategy needs `n_window=30` 15-minute bars (= 7.5 hours of cointegrated trading) plus warm-up to compute its z-score. A 0-day window collapses to ≈0 tradable bars and the engine's minimum-bars check correctly refuses to run.

These are the boundary cases of the `ncoint >= N + 2` qualification rule meeting the strategy's bar requirement. Per the operator's N=5 framing ("propose a value justified by trading logic, then report the implications"), this 3% silent-skip rate is treated as a documented implication, not a defect to optimize around. The skipped directives leave a clear audit trail in `backtest_directives/completed/` for re-running if a longer-window strategy variant is ever tested against the same spans.

**Follow-up deferred to a separate session (2026-05-30):** the per-strategy warmup pre-extension mechanism in `tools/run_stage1.py:259` (`RESOLVED_WARMUP_BARS`) was not ported to the basket pipeline (`tools/basket_data_loader._load_symbol_5m` strictly filters to `[start_date, end_date]`). Wiring it in would recover most of the 15 zero/short-window directives. Spawned as a separate task chip with full implementation plan; not addressed in this session to keep the v2 baseline frozen.

---

## 6. Corpus aggregation — 2026-05-30

Per-batch sanity check via `tools/cointegration_aggregator.py`. CSV at `/tmp/v2_corpus_aggregate.csv` (473 rows). Verdict buckets are REPORTING ONLY — the ledger stores no `verdict` column; ranking is by Ret/DD.

### 6.1 Pair-class breakdown

| Cohort | n | pos% | net% mean / med | ret/dd mean | win% mean | WINNER | NEUTRAL | LOSER | BLOWUP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **ALL** | 473 | 52% | +0.2 / +0.1 | 0.41 | 51.8 | 169 | 176 | 108 | 20 |
| FX-FX | 127 | **62%** | +0.8 / +0.3 | 0.54 | 56.4 | 42 | 71 | 14 | **0** |
| IDX-IDX | 56 | 43% | +0.3 / 0.0 | 0.50 | 48.9 | 18 | 20 | 17 | 1 |
| FX-IDX | 218 | 50% | +0.3 / 0.0 | **0.28** | 49.3 | 84 | 69 | 57 | 8 |
| CRYPTO/METAL | 72 | 46% | **-1.7** / -0.1 | 0.52 | 53.5 | 25 | 16 | 20 | **11** |

### 6.2 Cohort read

- **FX-FX is the cleanest cohort.** 62% positive, zero blowups, highest mean net% (+0.8) and win% (56.4). Consistent with prior memory's "FX-FX (62% pos)" baseline at v1 — the cohort-level edge survives the math correction + N=5 confirmation tightening.
- **CRYPTO/METAL keeps its fat-tail signature.** 11/72 = 15.3% blowup rate dominates the mean net% (-1.7%); median is only -0.1%. The cohort has wins but tail-risk swamps them at the mean.
- **FX-IDX is the largest slice (218 ep) and the weakest by ret/dd (0.28).** Matches prior memory's "CROSS hostile" pattern (`[[project_pine_n30_falsified]]`); the v2 corpus reaffirms it.
- **IDX-IDX dropped vs prior v1-era memory** (43% pos vs prior 67%). The v2 hysteresis classifier + N=5 confirmation is stricter; marginal IDX-IDX spans that survived v1 ADF now drop out, leaving a thinner but lower-quality residue.

### 6.3 Top 5 by ret/dd

| Pair | net% | ret/dd | win% | Window |
|---|---:|---:|---:|---|
| BTCUSD/GBPJPY | +0.2 | +21.17 | 0% | 2025-10-27 → 2025-10-28 *(tiny sample, ignore)* |
| ESP35/GER40 | +2.8 | +5.61 | 0% | 2024-11-28 → 2024-12-03 *(small sample)* |
| AUDJPY/USDCHF | +9.1 | +5.20 | 62% | 2026-03-11 → 2026-04-03 |
| EUSTX50/FRA40 | +8.0 | +4.77 | 69% | 2026-02-26 → 2026-04-30 |
| AUDNZD/GER40 | +13.2 | +4.25 | **100%** | 2026-04-21 → 2026-04-28 |

The clean entries (AUDJPY/USDCHF, EUSTX50/FRA40, AUDNZD/GER40) all have multi-week windows + double-digit win%. AUDJPY/USDCHF matches the [[project_pine_n30_usdchf_hedge_family]] sub-family pattern.

### 6.4 Bottom 5 by ret/dd

All five floor at ret/dd = −1.00 (full DD stop-outs, 0% win) on 1–3 day windows — the short-window tail that survived the warmup-bars gap (§4.5). Their inclusion is bounded but they pull the mean down at the FX-IDX cohort. If/when the warmup-bars fix lands, these specific episodes likely re-run with different outcomes.

### 6.5 Next analytical step (operator gate)

The aggregator is reporting-only by design (no verdict written to ledger). The v2 baseline is in place; the natural next step is operator-gated selection — pick the WINNER cohort (n=169 across all classes) and decide which warrant promotion to portfolio research, or which subsets warrant a focused re-test under a candidate strategy variant. No automated next step.

---

## 5. Ready for v2 corpus execution

The 527 v2 directives in `backtest_directives/cointrev_v3_staging/` can now be promoted to `inbox/` and executed:

```bash
# Move all v2 staging directives to inbox
mv backtest_directives/cointrev_v3_staging/*.txt backtest_directives/inbox/

# Run with parallel batching
python tools/run_pipeline.py --all --max-parallel 8
```

The v2 corpus will land in `cointegration_sheet` with `methodology_version='v2_log_eg'`. The cohort separation from the residual 68 v1 tombstones is automatic — the screener / view / aggregator all filter by `methodology_version`.

---

## 6. Audit references (final)

- [v1_run_ids_retired_2026-05-30.txt](../../cointegration_v1_retirement/v1_run_ids_retired_2026-05-30.txt) — 398 retired v1 rows (run_id | directive_id | pair_a | pair_b | is_current | completed_at_utc)
- [v1_backtest_folders_deleted_2026-05-30.txt](../../cointegration_v1_retirement/v1_backtest_folders_deleted_2026-05-30.txt) — 330 deleted backtests/ folders
- [v1_runs_folders_deleted_2026-05-30.txt](../../cointegration_v1_retirement/v1_runs_folders_deleted_2026-05-30.txt) — 323 deleted runs/<run_id>/ folders
- [raw_only_orphans_deleted_2026-05-30.txt](../../cointegration_v1_retirement/raw_only_orphans_deleted_2026-05-30.txt) — 18 deleted raw-only orphans (unrelated ad-hoc residue)
- [Methodology change](COINTEGRATION_SCREEN_MATH_V2.md) — log-price Engle-Granger + MacKinnon criticals (replaces raw-price ADF)
- [Backfill execution log](COINTEGRATION_SCREEN_BACKFILL_V2.md) — BC1-BC4 phases
- [Generator](../../../tools/generate_cointrev_v3_directives.py) — N=5 + onset+6 entry + break+1 exit convention
- CLAUDE.md Invariant #2 — operator-driven cleanup authority for the append-only ledger

---

## 5. Audit references

- v1 retired run_ids: see [v1_run_ids_retired_2026-05-30.txt](../../cointegration_v1_retirement/v1_run_ids_retired_2026-05-30.txt) (full enumeration of the 398 ledger rows)
- Methodology change rationale: [COINTEGRATION_SCREEN_MATH_V2.md](COINTEGRATION_SCREEN_MATH_V2.md)
- Backfill execution log: [COINTEGRATION_SCREEN_BACKFILL_V2.md](COINTEGRATION_SCREEN_BACKFILL_V2.md)
- Generator + look-ahead-safe convention: [generate_cointrev_v3_directives.py](../../../tools/generate_cointrev_v3_directives.py)
- Append-only ledger exception authority: CLAUDE.md Invariant #2 (operator-driven cleanup via `repair_integrity.py --action drop`)
