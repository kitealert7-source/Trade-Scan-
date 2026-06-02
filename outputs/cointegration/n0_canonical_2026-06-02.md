# COINTREV span-admission gate -- N=0 vs N=3 vs N=5 canonical aggregate + per-day shape

**Date:** 2026-06-02 | **Methodology:** v2_log_eg | **Cohort isolation:** explicit directive_id set per cohort (never the shared methodology tag)

## Cohort sizes (in-sheet)

- N=5 baseline (locked): **465** rows in cointegration_sheet (491 staged; 26 missing, 5.3% per `no-per-bar-parquet` skip class)
- N=3 variant (today AM): **551** rows in cointegration_sheet (582 staged; 31 missing, 5.3%)
- N=0 variant (today PM): **801** rows in cointegration_sheet (887 staged; 86 missing, 9.7% -- higher because more very-short spans)

**Skip-rate asymmetry caveat.** N=0 admits spans with ncoint as low as 2 days; the per-bar parquet skip class hits these
more often. Aggregate N=0 cohort is therefore slightly biased toward 'spans that produced a per-bar parquet' (correlated with span length).
Per-day-since-onset shape (Section B) is unaffected -- bucketizes WITHIN each backtest's trades.

## A. Canonical aggregate by pair-class -- 3-way comparison

All metrics from `cointegration_sheet.canonical_*` (research grade; NOT CORE/WATCH/FAIL governance verdicts).

| Pair-class | Cohort | n | %pos | net%_med | Ret/DD_mean | win%_mean | blowups(dd>30) |
|---|---|---:|---:|---:|---:|---:|---:|
| FX-FX | N=5 | 135 | 56% | +0.18 | +0.41 | 52.3 | 0 |
| FX-FX | N=3 | 168 | 54% | +0.12 | +0.40 | 51.9 | 0 |
| FX-FX | N=0 | 270 | 50% | +0.03 | +0.34 | 49.8 | 0 |
| IDX-IDX | N=5 | 54 | 48% | +0.00 | +0.43 | 54.4 | 1 |
| IDX-IDX | N=3 | 61 | 51% | +0.19 | +0.50 | 56.8 | 1 |
| IDX-IDX | N=0 | 99 | 42% | -0.18 | +0.22 | 53.1 | 1 |
| FX-IDX | N=5 | 204 | 51% | +0.23 | +0.25 | 55.8 | 8 |
| FX-IDX | N=3 | 236 | 51% | +0.06 | +0.25 | 54.9 | 8 |
| FX-IDX | N=0 | 305 | 48% | -0.06 | +0.25 | 53.9 | 8 |
| CRYPTO/METAL | N=5 | 72 | 49% | +0.00 | +0.51 | 54.4 | 11 |
| CRYPTO/METAL | N=3 | 86 | 42% | -0.30 | +0.23 | 55.2 | 12 |
| CRYPTO/METAL | N=0 | 127 | 46% | +0.00 | +0.17 | 51.9 | 14 |

## A.delta: N=0 minus N=5 (does dropping the gate help or hurt at the canonical aggregate level?)

| Pair-class | %pos delta | net%_med delta | Ret/DD_mean delta | blowups delta | Aggregate verdict |
|---|---:|---:|---:|---:|---|
| FX-FX | -5.2pp | -0.16 | -0.07 | +0 | **N=5 BETTER (gate IS filtering noise)** |
| IDX-IDX | -5.7pp | -0.18 | -0.21 | +0 | **N=5 BETTER (gate IS filtering noise)** |
| FX-IDX | -2.8pp | -0.29 | +0.00 | +0 | **no meaningful change** |
| CRYPTO/METAL | -2.2pp | +0.00 | -0.34 | +3 | **N=5 BETTER (gate IS filtering noise)** |

## B. Per-day-since-onset shape (N=0 corpus, per-leg trade attribution)

**Now extends back to days 1, 2, 3** -- the region only N=0 reaches.
`day N` = trade entered on the Nth business day after onset of cointegration regime.

| Class / metric | day 1 | day 2 | day 3 | day 4 | day 5 | day 6 | day 7-9 | day 10-14 | day 15-30 | day 31+ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **FX-FX win%** | 53.3 | 56.2 | 56.4 | 51.9 | 52.9 | 49.5 | 56.7 | 54.9 | 56.7 | 56.1 |
| FX-FX mean pnl | -0.01 | +0.17 | +0.10 | -0.15 | -0.07 | -0.11 | +0.20 | +0.04 | +0.19 | +0.13 |
| FX-FX median pnl | +0.16 | +0.29 | +0.31 | +0.08 | +0.10 | -0.02 | +0.31 | +0.23 | +0.27 | +0.25 |
| FX-FX n_legs | 1089 | 752 | 674 | 601 | 563 | 523 | 1368 | 1646 | 2699 | 2067 |
| **IDX-IDX win%** | 57.1 | 53.3 | 47.1 | 54.3 | 58.0 | 52.0 | 56.3 | 54.9 | 52.6 | 52.4 |
| IDX-IDX mean pnl | -0.16 | +0.17 | -0.26 | +1.28 | +1.38 | -0.87 | +0.08 | +0.14 | +0.06 | +0.03 |
| IDX-IDX median pnl | +0.53 | +0.35 | -0.15 | +0.56 | +0.70 | +0.25 | +0.64 | +0.59 | +0.35 | +0.29 |
| IDX-IDX n_legs | 420 | 255 | 208 | 208 | 169 | 150 | 449 | 546 | 1067 | 1156 |
| **FX-IDX win%** | 56.2 | 55.5 | 54.1 | 53.5 | 52.9 | 51.2 | 54.5 | 55.9 | 55.5 | 53.7 |
| FX-IDX mean pnl | +0.07 | +0.25 | +0.35 | +0.26 | -0.17 | -0.08 | +0.55 | +0.29 | +0.05 | -0.08 |
| FX-IDX median pnl | +0.40 | +0.41 | +0.35 | +0.23 | +0.29 | +0.06 | +0.27 | +0.40 | +0.44 | +0.28 |
| FX-IDX n_legs | 1350 | 961 | 909 | 840 | 765 | 717 | 1705 | 2310 | 4893 | 4771 |
| **CRYPTO/METAL win%** | 54.9 | 55.0 | 56.7 | 57.4 | 51.7 | 54.5 | 56.3 | 55.1 | 53.7 | 53.4 |
| CRYPTO/METAL mean pnl | -16054.20 | -7435.48 | -12153.62 | -530.50 | -14432.09 | -665.93 | -11079.40 | -1592.46 | -6060.45 | -957.35 |
| CRYPTO/METAL median pnl | +0.74 | +0.79 | +1.02 | +0.62 | +0.18 | +0.48 | +0.62 | +0.55 | +0.45 | +0.50 |
| CRYPTO/METAL n_legs | 603 | 431 | 390 | 340 | 300 | 279 | 758 | 915 | 1457 | 1318 |

## Synthesis

**The operator question** (does span admission improve results or only reduce opportunities?) is now answered at the pipeline-canonical level for each pair-class.

Read A.delta (aggregate verdict from canonical metrics) ALONGSIDE B (per-day shape).
- A.delta = the deployment-level question: does dropping the gate to N=0 help or hurt overall corpus stats?
- B = the mechanistic-shape question: WHERE on the entry-day curve does edge live?
- The two together: pipeline confirms (or refutes) probe-inferred shape AND tells us the actual rule-change implications.

**Next-course (operator):** p-value tightening (0.05 -> 0.02 / 0.03) -- upstream admission lever, complementary to confirmation-window.