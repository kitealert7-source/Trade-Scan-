# Phase 2 — SQLite Layer Manifest

**Status:** CODE-COMPLETE + UNIT-TESTED + REAL-DATA VALIDATED — 2026-05-20
**Note:** Paths in this document reflect the post-2026-05-20 architectural correction (SQLite moved from `TradeScan_State/cointegration/` to `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/` for backtest read convenience — see spec §4b).
**Spec:** [COINTEGRATION_SCREENER_V1_SPEC.md §5b, §7, §12](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)
**Gate cleared:** Phase 3 (Excel formatter profile) may begin.

---

## Deliverables

| File | Lines | Purpose |
|---|---|---|
| `tools/cointegration_db.py` | ~310 | Parquet → SQLite upsert with enrichment. CLI + library. Mirrors `tools/ledger_db.py` API conventions. |
| `tests/test_cointegration_db.py` | ~210 | 18 unit tests covering: schema/WAL/indexes, parquet→DB roundtrip (the gate test), hysteresis classifier (5 cases), rolling-median enrichment, history-aware upsert, idempotency on PK conflict, query ordering. |

## Test gate (from spec §12)

> "unit test: parquet→DB→DataFrame roundtrip preserves all columns"

Result: **18/18 passing in 2.37s**, including the explicit `TestRoundtrip::test_two_row_roundtrip` which loads a fixture parquet, upserts via `upsert_from_parquet`, queries back via `query_today`, and verifies all 19 `DB_COLUMNS` are present with values preserved (within float tolerance).

```
TestSchema (4 tests)              PASSED  table + indexes + WAL + column-order freeze
TestRoundtrip (2 tests)           PASSED  parquet→DB column preservation + as_of derivation
TestHysteresisClassifier (5)      PASSED  bootstrap + persistent-cointegrated +
                                          insufficient-priors + breaking-zone + broken-zone
TestRollingMedian (2 tests)       PASSED  no-priors → None, ≤5 priors used
TestUpsertSemantics (5 tests)     PASSED  query ordering + before-filter +
                                          enrichment-uses-history + idempotency +
                                          history-query-ordering
```

## First real run

```
[cointegration_db] upserted 306 rows into C:\...\data_root\SYSTEM_FACTORS\FX_COINTEGRATION\cointegration.db
[cointegration_db] today's regime counts:
regime         breaking  broken  cointegrated
lookback_days
252                  24      71            58
504                  19     102            32
```

## SQLite roundtrip verification (EURUSD/NZDUSD)

| Window | adf_pvalue | rolling_median | regime |
|---|---|---|---|
| 252 | 0.0856 | NULL | breaking |
| 504 | 0.1100 | NULL | broken |

Values match the parquet exactly; `pvalue_rolling_median_5d` is `NULL` because no prior daily history exists in SQLite yet (correct per spec §14 item 4 — the column will populate from day 6 onwards once 5 prior daily snapshots accumulate).

## Architecture compliance check

Spec §3 source-of-truth hierarchy enforced by code structure:

| Field | Source |
|---|---|
| `adf_pvalue`, `adf_statistic`, `half_life_days`, `hedge_ratio`, `current_zscore`, `sample_size`, `window_*` | Copied from parquet unchanged |
| `as_of` | Derived from `window_end` (date part) |
| `inserted_at` | Current UTC time (audit only) |
| **`pvalue_rolling_median_5d`** | **SQLite history query** (5 prior snapshots before today, for same pair-window) |
| **`regime`** | **Hysteresis-aware classifier** using current `adf_pvalue` + same SQLite history |

The two enrichment columns derive from SQLite's OWN history — never from re-running compute. parquet remains the deterministic source of truth.

## Hysteresis classifier behavior (spec §7)

Implementation in `classify_regime(current_pvalue, prior_pvalues)`:

| Condition | Returns |
|---|---|
| Fewer than 5 priors | Bootstrap path: `<0.05` → cointegrated, `<0.10` → breaking, else broken |
| Current ≥ 0.10 | `broken` (dominates regardless of history) |
| Current < 0.05 AND ≥ 4 of 5 priors also < 0.05 | `cointegrated` |
| Otherwise | `breaking` |

This prevents:
- Day-to-day flip-flop when p-value crosses 0.05 once
- "Cointegrated" classification on a single spike of significance after a long broken period

## Key behavioral guarantees (covered by tests)

1. **Idempotency** — running upsert twice on the same parquet → 2 rows (not 4). `INSERT OR REPLACE` on the PK `(as_of, pair_a, pair_b, tf, lookback_days)`.
2. **No self-influence** — enrichment uses `as_of < today's as_of`, so a re-run of today's snapshot doesn't see its own prior insert in the median/classifier calculation.
3. **History query order** — `query_for_classifier` returns most-recent-first; `query_history` returns oldest-first (for Excel "History" sheet rendering).

## What's NOT in Phase 2 (deferred to later phases)

| Item | Phase |
|---|---|
| Excel rendering with conditional formatting | Phase 3 |
| Ranking score (`stability × half_life × excursion`) | Phase 3 (computed at render time, not stored) |
| Daily scheduled task XML for full pipeline (compute + upsert) | Phase 4 |
| 7-day operator observation period | Phase 4 |

## Files now in production layout

```
data_root/SYSTEM_FACTORS/FX_COINTEGRATION/
    coint_1d_latest.parquet              (306 rows, ~30 KB, Phase 1)
    metadata.json                         (Phase 1)

data_root/SYSTEM_FACTORS/FX_COINTEGRATION/
    cointegration.db                      (306 rows, 128 KB, Phase 2)
    Cointegration_Screener.xlsx           (added in Phase 3)
```

## How to re-run Phase 2

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
# Compute fresh parquet, then mirror to SQLite:
python tools/cointegration_screen.py
python tools/cointegration_db.py --upsert

# Query today's snapshot from SQLite:
python tools/cointegration_db.py --query-today
```

Unit tests:

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
python -m pytest tests/test_cointegration_db.py -v
```

## Pacing notes for Phase 3

- Excel formatter profile `"cointegration"` to be added to `tools/excel_format/rules.py`.
- Three sheets per the spec §9: `Today`, `History`, `Notes`.
- Ranking score (§8 composite) computed at render time from SQLite — does NOT need a new column in either parquet or SQLite (it's a function of stored stats + ≥90 days of history, both already available).
- `format_excel_artifact.py --profile cointegration --file ...` to be the operator-facing CLI, matching the existing convention.
