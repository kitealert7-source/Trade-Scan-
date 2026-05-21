> ⚠ **POLLUTED — COINTREV v1 retired 2026-05-21.**
>
> This report measures calendar overlap of trades produced by the
> equal-lot COINTREV v1 strategy + P01 universe filter (`mean_beta > 0`,
> `0.10 < corr < 0.85`). Because the strategy didn't construct the
> cointegrating portfolio (no β-weighting), and the P01 filter selected
> correlation-pair-trade-friendly pairs, the trade clusters reflected
> here are NOT cointegration-mean-reversion clusters. Retained for audit.
> Full retirement story in `COHORT_REPORT.md` header.
>
> ---

# COINTREV Calendar-Overlap Analysis — C5 addition

**Generated:** 2026-05-20T13:56:17.574474+00:00
**Purpose:** Even without a true portfolio engine, this tells us whether
opportunities are naturally diversified across pairs OR concentrated in the
same macro windows. Critical for any future real-capital portfolio modeling.

## Cohort time-in-position summary

- Total bars in window: **49,785**
- Bars with ≥1 directive open: **15,896** (31.9%)

## Peak concurrency

- **Peak count: 6 directives open simultaneously**
- First hit at: 2024-12-27 04:15:00
- Bars at peak level: 14

### Cluster composition at first peak

| directive_id | direction | pair |
|---|---|---|
| 91_PORT_AUDNZDAUDUSD_15M_COINTREV_S01_V1_P00 | short | AUDNZD/AUDUSD |
| 91_PORT_AUDNZDAUDUSD_15M_COINTREV_S41_V1_P01 | short | AUDNZD/AUDUSD |
| 91_PORT_AUDNZDNZDUSD_15M_COINTREV_S07_V1_P00 | short | AUDNZD/NZDUSD |
| 91_PORT_AUDUSDEURAUD_15M_COINTREV_S11_V1_P00 | short | AUDUSD/EURAUD |
| 91_PORT_EURUSDUSDJPY_15M_COINTREV_S31_V1_P00 | short | EURUSD/USDJPY |
| 91_PORT_EURUSDUSDJPY_15M_COINTREV_S32_V1_P00 | long | EURUSD/USDJPY |

## Concurrency histogram (bars per concurrency level)

| concurrent count | bars | % of all bars | wall-clock |
|---:|---:|---:|---|
| 0 | 33,889 | 68.07% | 8472.2h |
| 1 | 10,581 | 21.25% | 2645.2h |
| 2 | 3,872 | 7.78% | 968.0h |
| 3 | 1,098 | 2.21% | 274.5h |
| 4 | 296 | 0.59% | 74.0h |
| 5 | 35 | 0.07% | 8.8h |
| 6 | 14 | 0.03% | 3.5h |

## Top 20 days by max concurrency

| date | max concurrent that day |
|---|---:|
| 2024-12-27 | 6 |
| 2024-11-04 | 5 |
| 2025-07-15 | 4 |
| 2025-07-31 | 4 |
| 2026-04-28 | 4 |
| 2025-07-22 | 4 |
| 2025-07-24 | 4 |
| 2025-07-30 | 4 |
| 2025-07-29 | 4 |
| 2026-05-13 | 4 |
| 2026-05-05 | 4 |
| 2026-05-06 | 4 |
| 2026-05-18 | 4 |
| 2026-04-27 | 4 |
| 2026-05-12 | 4 |
| 2026-04-23 | 4 |
| 2025-01-08 | 4 |
| 2024-10-08 | 4 |
| 2024-09-19 | 4 |
| 2025-07-18 | 4 |

## Interpretation hints

- **If peak concurrency ≈ N (cohort size)** → all opportunities cluster in same macro windows; real-capital deployment hits hard concurrency wall.
- **If peak concurrency is small (e.g. 2-5 of 40)** → opportunities naturally diversified across time; real-capital strategy more viable with modest position-count cap.
- **If 1-concurrency dominates the histogram** → most of the time only one pair is active; portfolio benefits are mostly statistical (smoothing) rather than parallel-deployment.
- **Long-tail cluster composition** (many distinct combinations at peak) → no single 'overlap regime'; concentration is sporadic.
- **Repeat cluster composition** (same N pairs at peak each time) → a small structural group drives most of the cohort's activity.