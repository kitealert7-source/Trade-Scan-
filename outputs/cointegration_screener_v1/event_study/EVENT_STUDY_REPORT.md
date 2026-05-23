> ℹ **v2.1 — first POSITIVE qualification lift in the post-FX universe (2026-05-23).**
>
> This is the **v2.1 re-run** triggered the same day as v2, after the universe
> was expanded again to add **10 equity indices** (SPX500, NAS100, US30,
> UK100, FRA40, ESP35, EUSTX50, GER40, JPN225, AUS200). The motivating
> hypothesis: FX-equity cointegrations are economically grounded (USD-strength
> and risk-on/risk-off shared drivers) and may surface the qualification edge
> that v2 lost when methodology was corrected.
>
> ### Headline by version
>
> | version | universe              | pair-pairs | τ=2.0 qual rev | baseline rev | lift   |
> |---      |---                    |---:        |---:            |---:           |---:    |
> | v1      | 18 FX, inner-join     | 153        | 37.0%           | 26.9%         | +10.1pp |
> | v2      | 21 sym, per-pair      | 210        | 26.5%           | 28.4%         | −1.9pp  |
> | **v2.1**| **31 sym, per-pair**  | **465**    | **26.4%**       | **29.8%**     | **−3.3pp** |
>
> At τ=2.0 the v2.1 lift is still negative — but the picture changes at higher
> thresholds. The auto-generated body below now picks τ=3.0 as the suggested
> threshold because that is the first τ in the expanded universe where the
> qualified cohort beats the baseline:
>
> | τ        | qual rev | base rev | lift     | n (qual) |
> |---:      |---:      |---:      |---:      |---:      |
> | 1.5      | 27.8%    | 37.8%    | −10.0pp  | 176      |
> | 2.0      | 26.4%    | 29.8%    | −3.3pp   | 121      |
> | 2.5      | 25.3%    | 26.1%    | −0.8pp   | 91       |
> | **3.0**  | **28.1%**| 24.2%    | **+3.9pp**| **32**  |
>
> ### Decomposition by asset-class pairing (the real story)
>
> The aggregate lift number averages across very different sub-cohorts.
> Splitting the **qualified** cohort by pair class at τ=2.5 (largest qualified
> cohort with statistical power):
>
> | pair class | n   | qual rev | baseline rev | lift     |
> |---         |---: |---:      |---:           |---:      |
> | **FX+IX**  | **26** | **38.5%** | 25.0%      | **+13.5pp** |
> | CC+FX      | 7   | 28.6%    | 28.0%        | +0.6pp   |
> | FX+FX      | 50  | 20.0%    | 25.2%        | −5.2pp   |
> | IX+IX      | 8   | 12.5%    | 25.4%        | −12.9pp  |
>
> And at τ=3.0:
>
> | pair class | n   | qual rev | baseline rev | lift     |
> |---         |---: |---:      |---:           |---:      |
> | **FX+IX**  | **11** | **36.4%** | 22.3%      | **+14.1pp** |
> | FX+FX      | 17  | 17.6%    | 24.2%        | −6.6pp   |
> | IX+IX      | 2   | 50.0%    | 23.8%        | +26.2pp (small N) |
>
> **The aggregate positive lift at τ=3.0 is driven primarily by the FX-equity
> sub-cohort.** FX-FX still shows negative lift (consistent with v2). Equity-
> equity qualified events fail catastrophically at low thresholds (0% reversion
> at τ=1.5 and τ=2.0) — qualification selects equities that *stay* divergent.
>
> ### Strongest FX-equity reverters (qualified τ≥2.0, n≥3)
>
> | pair                | n | qual rev |
> |---                  |---:|---:     |
> | AUDNZD / US30       | 4 | 100.0%   |
> | EURUSD / US30       | 3 | 100.0%   |
> | AUDNZD / NAS100     | 4 | 75.0%    |
> | GBPNZD / SPX500     | 5 | 40.0%    |
> | EUSTX50 / GBPNZD    | 6 | 33.3%    |
> | AUDNZD / JPN225     | 4 | 25.0%    |
> | ESP35 / EURGBP      | 3 | 0.0%     |
> | EUSTX50 / USDCHF    | 3 | 0.0%     |
> | FRA40 / GBPNZD      | 3 | 0.0%     |
> | GBPNZD / US30       | 3 | 0.0%     |
> | GBPUSD / SPX500     | 3 | 0.0%     |
>
> Sample sizes per pair are small (4-6 events over ~10y), so any single-pair
> conclusion is noise-dominated. Treat as exploratory candidates pending
> per-pair sanity checks, not validated signals.
>
> ### Currently cointegrated FX-equity pairs (today's screener, both windows)
>
> 18 FX-IX pairs pass ADF p<0.05 in BOTH the 252d and 504d windows on
> 2026-05-23. Cluster patterns:
>
> 1. **FRA40 (CAC 40) is the most-connected index** — 7 cointegrations
>    spanning AUDJPY, AUDNZD, CADJPY, CHFJPY, EURGBP, EURJPY, EURUSD.
> 2. **Yen-cross/equity-index cluster:** AUDJPY/FRA40, CADJPY/FRA40,
>    CHFJPY/EUSTX50, CHFJPY/FRA40, CHFJPY/JPN225, CHFJPY/UK100,
>    EURJPY/FRA40, EURJPY/UK100, EURJPY/US30, GBPJPY/UK100, GBPJPY/US30.
>    Economic interpretation: yen safe-haven dynamic + equity risk sentiment
>    share a common factor, so spreads form persistent statistical
>    relationships. Strongest grouping in the entire dataset.
> 3. **CHFJPY** alone has 4 cointegrations (EUSTX50, FRA40, JPN225, UK100) —
>    pure safe-haven-cross-asset pair.
>
> The strongest FX-IX reverters from the event study (AUDNZD/US30,
> EURUSD/US30, AUDNZD/NAS100) are NOT in today's BOTH-window cointegrated
> set — those qualifications were transient over the 10y window, not
> stable today.
>
> ### Implications for the deferred β-weighted COINTREV v1.2 strategy build
>
> 1. **A β-weighted strategy on FX-FX pairs has no documented edge**, per v2.
>    Both v2 and v2.1 confirm: FX-FX qualified events under-perform baseline.
> 2. **A β-weighted strategy on FX-equity pairs has a possible 13-14pp edge**
>    at τ≥2.5, but sample size is thin (26-11 events over a decade) and
>    edge is currently concentrated in a handful of specific pairs.
> 3. **Equity-equity is a no-go** at the universe level — qualified IX-IX
>    pairs systematically fail to revert.
> 4. **Operational suggestion if pursued:** focus a β-weighted backtest on the
>    18 currently-cointegrated FX-IX pairs, especially the FRA40 cluster and
>    the yen-cross/equity-index cluster. Expect on the order of 30-60 trades
>    over 5 years (low frequency), with target reversion ~30-35% and entry
>    threshold τ≥2.5. The "thin-edge / low-frequency" profile is similar to
>    the failed COINTREV v1 — viability hinges on stop discipline (p90 adverse
>    excursion 1.4-1.7 z-units → hard stop near |z|≈4 catches 90% of failures).
>
> ### Caveats (all v2 caveats still apply)
>
> - In-sample β and z-score — no OOS hedge ratio validation.
> - Monthly ADF anchors — qualification can be off by up to 21 days.
> - 60-bar forward window arbitrary.
> - `qual_break_rate` 95-100% — regime degrades during forward window.
> - Indices have only ~10y of OctaFX data (GER40: ~3y) — pre-2016 cross-asset
>   behavior is not in this sample.
> - Per-pair history start dates vary — not strictly apples-to-apples.
> - Small N per pair → exploratory only, not statistical validation.
>
> ### Version archives
>
> - [`EVENT_STUDY_REPORT_v1_18fx_inner.md`](EVENT_STUDY_REPORT_v1_18fx_inner.md)
>   — original 2026-05-20 run, 18-symbol FX universe, inner-join.
> - [`EVENT_STUDY_REPORT_v2_21sym_union.md`](EVENT_STUDY_REPORT_v2_21sym_union.md)
>   — 2026-05-23 morning run, 21 symbols, per-pair UNION alignment.
> - This file (`EVENT_STUDY_REPORT.md`) — 2026-05-23 afternoon run, 31 symbols.
>
> ---

# Cointegration Event Study — Concept Validation (v2.1, 2026-05-23)

**Generated:** 2026-05-23T05:21:23.367603+00:00  
**Spec reference:** [`COINTEGRATION_SCREENER_V1_SPEC.md`](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)

## Hypothesis under test

> Do structurally persistent FX relationships (cointegrated in BOTH 252d and 504d windows, qualification held as-of event) exhibit reliable forward mean-reversion after abnormal spread displacement, before structural regime degradation?

## Methodology

- **Universe:** 31 symbols (AUDUSD, EURUSD, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY, AUDJPY, AUDNZD, CADJPY, CHFJPY, EURAUD, EURGBP, EURJPY, GBPAUD, GBPJPY, GBPNZD, NZDJPY, XAUUSD, BTCUSD, ETHUSD, SPX500, NAS100, US30, UK100, FRA40, ESP35, EUSTX50, GER40, JPN225, AUS200), 465 unordered pair-pairs
- **Date range:** 1992-02-19 → 2026-05-23 (9343 calendar bars, UNION-aligned; per-pair sample = intersection of that pair's two legs)
- **Qualification:** ADF p < 0.05 at nearest **monthly anchor** ≤ event_bar−1 in **BOTH** 252d AND 504d windows
- **Hedge ratio:** rolling OLS over 252 bars (β_t = cov(b,a)/var(a))
- **Spread:** b_t − β_t·a_t
- **Z-score:** (spread_t − mean_t) / std_t over 252-bar window
- **Event:** first bar where |z| crosses ≥ τ from below AND pair qualified at t
- **Thresholds:** [1.5, 2.0, 2.5, 3.0]
- **Forward window:** 60 trading days
- **Reversion target:** |z| ≤ 1.0
- **No-lookahead invariant:** ADF anchor must be ≥ 1 bar before t (shift=1)

**Baseline cohort** (`all`): same event detection without cointegration filtering. Measures the LIFT of qualification — proves filtering does real work rather than selecting the same population a naive trader would.

## Cohort sizes

- Qualified-cohort events: **420** across all thresholds + pairs
- All-cohort events:        **22,603** (baseline)
- Filter retention:         **1.9%** (cointegration qualification removes 98.1% of events)

## Summary by threshold — QUALIFIED cohort

|   threshold |   n_events |   reversion_rate |   median_bars_to_reversion |   median_max_z_in_window |   median_adverse_excursion |   p90_adverse_excursion |   qual_break_rate |
|------------:|-----------:|-----------------:|---------------------------:|-------------------------:|---------------------------:|------------------------:|------------------:|
|         1.5 |        176 |            0.278 |                       36   |                    2.633 |                      1.069 |                   2.462 |             0.949 |
|         2   |        121 |            0.264 |                       34.5 |                    2.907 |                      0.85  |                   2.174 |             0.95  |
|         2.5 |         91 |            0.253 |                       33   |                    3.074 |                      0.556 |                   1.666 |             0.978 |
|         3   |         32 |            0.281 |                       39   |                    3.877 |                      0.737 |                   1.421 |             1     |

## Summary by threshold — ALL (baseline) cohort

|   threshold |   n_events |   reversion_rate |   median_bars_to_reversion |   median_max_z_in_window |   median_adverse_excursion |   p90_adverse_excursion |   qual_break_rate |
|------------:|-----------:|-----------------:|---------------------------:|-------------------------:|---------------------------:|------------------------:|------------------:|
|         1.5 |       9160 |            0.378 |                         33 |                    2.205 |                      0.659 |                   1.97  |                 0 |
|         2   |       6840 |            0.298 |                         39 |                    2.542 |                      0.493 |                   1.651 |                 0 |
|         2.5 |       4256 |            0.261 |                         41 |                    2.968 |                      0.406 |                   1.428 |                 0 |
|         3   |       2347 |            0.242 |                         43 |                    3.421 |                      0.356 |                   1.257 |                 0 |

## Reversion lift over baseline

|   threshold |   qualified_reversion_rate |   baseline_reversion_rate |   lift_percentage_points |
|------------:|---------------------------:|--------------------------:|-------------------------:|
|         1.5 |                      0.278 |                     0.378 |                   -9.976 |
|         2   |                      0.264 |                     0.298 |                   -3.32  |
|         2.5 |                      0.253 |                     0.261 |                   -0.806 |
|         3   |                      0.281 |                     0.242 |                    3.924 |

## Interpretation

- **Suggested threshold (qualified cohort):** τ = **3.0**
  - reversion rate 28.1% over 32 events
  - median bars-to-reversion 39
  - p90 adverse excursion 1.42 z-units past entry

- **Caveats:**
  - In-sample β and z-score windows — no out-of-sample validation of the hedge ratio
  - Monthly ADF sampling — qualification could be over/under-stated by up to 21 days
  - 60-bar forward window is arbitrary — longer windows would raise reversion rate AND mean-time-to-reversion
  - No trading-cost model — z-score reversion ≠ tradable P/L
  - Failure-mode skew: pairs that broke during the forward window are counted in `qual_break_rate`

## Files

- `event_summary_by_threshold.csv` — the summary tables above as CSV
- `events_detail.parquet` — every event as a row (cohort, pair, ts, threshold, all stats) for any follow-up slicing (per-pair, per-year, per-direction, etc.)
