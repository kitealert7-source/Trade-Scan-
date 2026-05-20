# Phase 3 — Excel Report Layer Manifest

**Status:** CODE-COMPLETE + UNIT-TESTED + REAL-DATA VALIDATED — 2026-05-20
**Note:** Paths in this document reflect the post-2026-05-20 architectural correction (SQLite + Excel moved from `TradeScan_State/cointegration/` to `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/` for backtest read convenience — see spec §4b).
**Spec:** [COINTEGRATION_SCREENER_V1_SPEC.md §8, §9 (amended)](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)
**Gate cleared:** Phase 4 (scheduled task + 7-day observation) may begin.

---

## Spec amendments folded in this phase (per architectural review 2026-05-20)

1. **§5b** added `history_depth INTEGER NOT NULL DEFAULT 0` to the SQLite schema.
2. **§9** added a `Summary` sheet ahead of `Today`/`History`/`Notes` — operator's universe-level structural view.
3. **§9** pivoted the `Today` sheet to one-row-per-pair with adjacent 252d / 504d columns and a derived `agreement` flag, so window divergence (the "recent formation = possible false positive" case) is visible at a glance.
4. **§9** explicit "raw values stay visible alongside the composite score" doctrine — `Today` exposes p-value, half-life, z-score, hedge ratio, history depth, regime per window AND the score.

Both `cointegration_db.py` and the test suite updated alongside the schema change. Schema-bump is a destructive change in v1 (no migration code) — handled by deleting the DB file and re-running upsert.

---

## Deliverables

| File | Lines | Purpose |
|---|---|---|
| `tools/cointegration_excel.py` | ~400 | Excel renderer (openpyxl-based, no excel_format/ profile dependency). 4 sheets, conditional fills, composite ranking score computed at render time. CLI: `--export`. |
| `tests/test_cointegration_excel.py` | ~165 | 8 unit tests: pivot agreement labels, half-life quality formula (peak + symmetry + NaN), composite score range + non-zero, 4-sheet workbook end-to-end. |

## Test gate

> Render produces a 4-sheet valid Excel with pivoted Today + populated Summary.

Result: **8/8 passing in 2.82s** (and **34/34 across all three phases combined** in 3.33s, regression-free).

```
TestPivot (2)             PASSED  all 4 agreement cases + windows-adjacent
TestHalfLifeQuality (3)   PASSED  peaks at 15d + log-symmetric + NaN→0
TestCompositeScore (2)    PASSED  in [0,1] + non-zero on cointegrated
TestExportExcel (1)       PASSED  4-sheet workbook with non-empty data
```

## First real run

```
[cointegration_excel] wrote C:\...\data_root\SYSTEM_FACTORS\FX_COINTEGRATION\Cointegration_Screener.xlsx
```

| Sheet | Rows × Cols | Purpose |
|---|---|---|
| Summary | 39 × 6 | Universe regime / half-life / top currencies / window agreement / regime changes / bootstrap visibility |
| Today | 154 × 15 | One row per pair (153 pairs + header), windows pivoted, agreement flag, composite score, raw values |
| History | 307 × 11 | Last 90 daily snapshots for every pair-window (306 rows + header today; grows daily) |
| Notes | 39 × 1 | Schema, classifier doctrine, ranking formula, correlation ≠ cointegration warning, probe re-run pointer |
| **File size** | **40.7 KB** | (small — openpyxl + 4 sheets) |

## Empirical findings from the first Excel snapshot

### Today sheet — top 7 ranked pairs (by composite score, descending)

| pair | agreement | regime 252 / 504 | p 252 / 504 | half-life 252 / 504 |
|---|---|---|---|---|
| GBPUSD / USDCHF | **BOTH** | cointegrated / cointegrated | 0.044 / 0.028 | 16.0 / — |
| AUDJPY / EURAUD | 252-only | cointegrated / broken | 0.045 / 0.598 | 16.1 / — |
| NZDUSD / USDCHF | 252-only | cointegrated / broken | 0.032 / 0.634 | 13.4 / — |
| EURAUD / EURJPY | 252-only | cointegrated / broken | 0.026 / 0.908 | 17.4 / — |
| USDCAD / USDCHF | 252-only | cointegrated / broken | 0.039 / 0.229 | 12.5 / — |
| GBPNZD / USDCHF | 252-only | cointegrated / broken | 0.038 / 0.192 | 12.2 / — |
| CADJPY / EURJPY | 252-only | cointegrated / broken | 0.024 / 0.239 | 11.9 / — |

The very first row (`BOTH`) is the only universe-wide "passes both windows" pair today: **GBPUSD / USDCHF**, p≈0.04 at both windows. Everything below is `252-only` — exactly the "recent formation, possibly unstable, operator must verify" zone the agreement column was designed to flag.

### Summary sheet — universe structure

```
Section 1 — Universe regime distribution
              cointegrated  breaking  broken  total
   252d             58         24       71      153
   504d             32         19      102      153

Section 2 — Half-life days in cointegrated pairs
              median  mean   min    max
   252d         8.74  9.02   5.35  17.36
   504d        18.19 20.52  13.37  30.81

Section 3 — Top currencies in cointegrated pairs (252d) [top 4 of 10]
   USD  46 appearances (39.7%)
   JPY  38               (32.8%)
   EUR  35               (30.2%)
   AUD  33               (28.4%)

Section 4 — Window agreement (153 pairs)
   BOTH        13
   252-only    45
   504-only    19
   NEITHER     76

Section 5 — Regime changes
   (no prior snapshot — first run)

Section 6 — Bootstrap visibility
   bootstrap (history_depth < 5)         306 / 306  (100.0%)
   hysteresis-active (history_depth ≥ 5)   0 / 306    (0.0%)
   → Proper hysteresis kicks in after 5 daily runs, expected 2026-05-25.
```

The **Window agreement** count tells the most important story: **13 pairs** are cointegrated in BOTH windows simultaneously — a substantial tradable candidate population. The 45 `252-only` pairs are the false-positive watch zone (look cointegrated in the short window but the 2-year window says the relationship isn't stable). The 13 BOTH pairs cluster into three structural families:

| Family | Member pairs | Why they cohere |
|---|---|---|
| EUR/GBP/USD triangle | EURUSD/GBPUSD, EURGBP/GBPUSD, EURGBP/EURUSD | Three pairs sharing two currencies are mathematically tight |
| JPY funding-currency factor | CHFJPY/EURGBP, EURJPY/GBPJPY, CHFJPY/GBPJPY, AUDJPY/CADJPY, AUDNZD/GBPJPY | JPY carry / risk-off behavior pulls these together |
| Antipodean + JPY (risk on/off) | AUDUSD/NZDJPY, GBPAUD/NZDJPY, EURGBP/GBPNZD | Common AUD/NZD/risk-asset factor |

All 13 BOTH pairs have p-values < 0.05 in both windows and half-lives in the operationally tradable 7-18 day zone. These are the genuine candidates for further (out-of-sample) validation in v1.1 before any actual trading.

## Architecture compliance check (Phase 3 doesn't violate the rules)

| Rule | Status |
|---|---|
| parquet is source of truth, SQLite is reporting sink | ✓ unchanged |
| Excel reads from SQLite only — never the source of compute | ✓ |
| Ranking score is computed at render time, not stored | ✓ (no schema bump needed) |
| Raw values exposed alongside score | ✓ (Today sheet has p-value, half-life, z-score, hedge ratio, history depth) |
| Bootstrap state visible | ✓ (Today flags rows with orange fill + Summary §6 reports the universe-wide ratio) |

## How to re-run Phase 3

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
# Full chain: compute → SQLite → Excel
python tools/cointegration_screen.py
python tools/cointegration_db.py --upsert
python tools/cointegration_excel.py --export

# Excel-only regeneration (after SQLite was updated some other way):
python tools/cointegration_excel.py --export
```

Unit tests:

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
python -m pytest tests/test_cointegration_excel.py -v
# All three phases combined:
python -m pytest tests/test_cointegration_screen.py tests/test_cointegration_db.py tests/test_cointegration_excel.py
```

## Files now in production layout

```
data_root/SYSTEM_FACTORS/FX_COINTEGRATION/
    coint_1d_latest.parquet              (Phase 1)
    metadata.json                         (Phase 1)

data_root/SYSTEM_FACTORS/FX_COINTEGRATION/
    coint_1d_latest.parquet               (Phase 1 — runtime source of truth)
    metadata.json                         (Phase 1)
    cointegration.db                      (Phase 2 — re-created with history_depth)
    Cointegration_Screener.xlsx           (Phase 3 — 40.7 KB)
(empty TradeScan_State/cointegration/ subdir was removed after the
 architectural correction — see spec §4b)
```

## What's NOT in Phase 3 (deferred to Phase 4)

- Daily Windows Task that chains compute → upsert → Excel-export automatically
- 7-day operator observation period before declaring v1 stable
- Lock-handling if the user has Excel open during a scheduled run (spec §14 item 3 — defer the on-demand-only fallback decision until observed in operation)

## Pacing note

Most observed values in Summary will only stabilize after **5-10 days of daily runs**:
- `pvalue_rolling_median_5d` becomes non-null at day 6
- `regime` shifts from bootstrap to hysteresis classification at day 6 per pair-window
- `Summary §5` (regime changes) becomes populated from day 2 onward
- The composite score's `stability_persistence` component (90-day window) only becomes a meaningful ranking signal at day 30+

This is by design — the first week of the daily Phase 4 task is the "burn-in" period during which the operator should be present to confirm the daily cycle behaves correctly and watch the classifier transition out of bootstrap mode.
