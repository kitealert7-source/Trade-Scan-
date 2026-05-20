# Phase 1 — Compute Engine Manifest

**Status:** CODE-COMPLETE + UNIT-TESTED + REAL-DATA VALIDATED — 2026-05-20
**Spec:** [COINTEGRATION_SCREENER_V1_SPEC.md §6, §12](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)
**Gate cleared:** Phase 2 (SQLite layer) may begin.

---

## Deliverables

| File | Lines | Purpose |
|---|---|---|
| `tools/cointegration_screen.py` | ~290 | Compute engine. CLI + library. Reads 18 daily-CSV symbol streams from MASTER_DATA, computes 153 pair-pair × 2 windows = 306 rows of stats, writes parquet + metadata.json. |
| `tests/test_cointegration_screen.py` | ~140 | 7 unit tests covering: cointegrated/random-walk synthetic pairs, alignment edge case, z-score bounds, run-to-run determinism, schema column-order freeze. |

## Test gate (from spec §12)

> "unit test: compute against fixed inputs produces byte-identical parquet (modulo `generated_at`)"

Result: **7/7 passing in 10.8s**, including the explicit `TestDeterminism::test_repeated_compute_on_same_input_is_identical` test.

```
TestComputePairStats::test_cointegrated_pair_passes_adf            PASSED
TestComputePairStats::test_random_walk_pair_fails_adf              PASSED
TestComputePairStats::test_too_few_aligned_bars_returns_none       PASSED
TestComputePairStats::test_zscore_within_expected_bounds           PASSED
TestDeterminism::test_repeated_compute_on_same_input_is_identical  PASSED
TestSchema::test_required_constants                                PASSED
TestSchema::test_parquet_columns_canonical_order                   PASSED
```

## First real run

Invoked from current (non-elevated) PowerShell session against full MASTER_DATA — succeeded without needing elevation, because `pandas.read_csv` accesses files via direct path (not directory enumeration, which is what triggers the ACL).

| Metric | Value |
|---|---|
| Universe | 18 FX pairs |
| Pair-pairs computed | 153 |
| Windows | {252, 504} daily bars |
| Total rows written | 306 |
| Wall time | 4.4s |
| Parquet | `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/coint_1d_latest.parquet` |
| Metadata | `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/metadata.json` |

### Regime distribution (Phase 1 bootstrap classifier)

| Window | broken | breaking | cointegrated |
|---|---|---|---|
| 252-bar (1y) | 71 (46%) | 24 (16%) | 58 (38%) |
| 504-bar (2y) | 102 (67%) | 19 (12%) | 32 (21%) |

The 2y window is stricter (fewer cointegrated pairs survive), as expected.

### Spec's "correlation ≠ cointegration" warning — empirically confirmed

The session's working example pair (EURUSD/NZDUSD) had **visual correlation of 0.79** on the live Pine indicator, suggesting strong relationship. The cointegration test gives:

| pair | window | p-value | regime |
|---|---|---|---|
| EURUSD/NZDUSD | 252 | 0.086 | breaking |
| EURUSD/NZDUSD | 504 | 0.110 | broken |

**Neither window passes the 0.05 cointegration threshold.** A z-score mean-reversion trade on this pair would have no statistical basis despite the visually compelling correlation. This is exactly the failure mode the §8 ranking doctrine ("do NOT rank by p-value") and §1 spec rationale were designed to prevent.

### Top truly cointegrated pairs (252-bar window, by ADF p-value)

```
pair_a pair_b  adf_pvalue  half_life_days  hedge_ratio    regime
NZDJPY USDCHF    0.000516           5.35    -0.003   cointegrated
EURAUD USDCHF    0.001438           6.36     0.133   cointegrated
EURAUD GBPAUD    0.001907           9.42     1.148   cointegrated
EURAUD EURGBP    0.002027           9.28     0.001   cointegrated
AUDUSD EURGBP    0.002205           9.30     0.008   cointegrated
GBPAUD USDCHF    0.002512           6.43     0.119   cointegrated
AUDJPY EURGBP    0.002966           9.26     0.000   cointegrated
AUDUSD USDCHF    0.003085           6.42    -0.377   cointegrated
AUDJPY USDCHF    0.003146           6.57    -0.001   cointegrated
CADJPY GBPJPY    0.003800           6.61     1.646   cointegrated
```

Mostly cross-pair combinations that share a currency leg — mathematically expected to cointegrate through the shared exposure. Half-lives 5-10 days are operationally tradable. **Do not trade on these blindly** — the §8 stability × half-life × excursion composite score (computed at Excel-export time in Phase 3) is the intended ranking, not raw p-value.

## Phase 1 simplifications (documented for Phase 2 to address)

| Column / Field | Phase 1 value | Phase 2 fix |
|---|---|---|
| `pvalue_rolling_median_5d` | always NaN | Backfill from SQLite history (5 prior daily snapshots) |
| `regime` | bootstrap classifier (current p-value only, no hysteresis) | Hysteresis-aware classifier using "≥4 of last 5 snapshots" rule from SQLite |

## Known TODOs (non-blocking, deferred to v1.1+)

1. **Lift `_load_native_closes`** from `tools/factors/fx_correlation_matrix.py` (currently a private function) into a shared module `tools/factors/_loaders.py`. Phase 1 imports the private function directly per spec guidance "for v1 just call it directly."
2. **Float64 → float32 dtype cast warning**. statsmodels OLS produces float64 internally; we cast on output. No correctness issue.

## How to re-run Phase 1

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
python tools/cointegration_screen.py                       # latest data
python tools/cointegration_screen.py --as-of 2026-05-19    # historical
python tools/cointegration_screen.py --no-write            # debug, no output
```

Unit tests:

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
python -m pytest tests/test_cointegration_screen.py -v
```
