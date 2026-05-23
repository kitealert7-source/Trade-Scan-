> ⚠ **v2 RE-VALIDATION — the v1 37% headline finding does NOT survive (2026-05-23).**
>
> This report is the **v2 re-run** mandated by the 2026-05-21 COINTREV strategy
> retirement (RESEARCH_MEMORY 2026-05-21 entry). Two methodology changes vs v1:
>
> 1. **Universe expanded** to 21 symbols (18 FX + XAUUSD + BTCUSD + ETHUSD) to
>    match the post-2026-05-21 screener. ETHUSD pair-pairs are auto-skipped:
>    insufficient history for the 504-bar long-window ADF.
> 2. **Per-pair alignment** instead of universe-wide intersection. v1 collapsed
>    all 18 FX to their common date range (2010-05 → 2026-05, 4074 bars). v2
>    aligns each pair-pair independently, so AUDUSD/EURUSD gets ~6500 bars from
>    1992, AUDUSD/XAUUSD gets ~6500 bars from 1992, AUDUSD/BTCUSD gets ~2200
>    bars from 2017. This is more honest but makes v1 and v2 NOT a controlled
>    comparison — the qualified-event populations differ in size AND vintage.
>
> ### Headline: the 37%-at-τ=2.0 reversion rate from v1 does NOT replicate
>
> | metric                              | v1 (18 FX, inner-join)  | v2 (21 sym, per-pair)  |
> |---                                  |---:                     |---:                    |
> | τ=2.0 qualified events              | 54                      | **83**                 |
> | τ=2.0 qualified reversion rate      | **37.0%**               | **26.5%**              |
> | τ=2.0 baseline reversion rate       | 26.9%                   | 28.4%                  |
> | τ=2.0 **lift over baseline**        | **+10.1pp**             | **−1.9pp**             |
> | τ=2.0 median bars-to-reversion (q)  | 45                      | 39                     |
> | filter retention                    | 1.9%                    | 2.0%                   |
>
> The qualified cohort at τ=2.0 now reverts LESS than the unfiltered baseline.
> Whatever edge the v1 study seemed to demonstrate, the methodology fix +
> universe expansion neutralizes it.
>
> ### Decomposition — it is NOT the cross-asset additions
>
> Cross-asset events (any pair-pair where XAUUSD or BTCUSD is a leg) at τ=2.0:
> 8 qualified events out of 83. Their reversion rate is 50%, slightly above
> the cohort average. FX-FX alone shows the same collapse:
>
> | τ=2.0 cohort        | n   | reversion rate |
> |---                  |---: |---:            |
> | v1 FX-FX (54 evts)  | 54  | 37.0%          |
> | v2 FX-FX (75 evts)  | 75  | **24.0%**      |
> | v2 cross-asset      | 8   | 50.0% (small N)|
>
> v2's FX-FX cohort generated 75 qualified events (vs v1's 54) by virtue of
> extending the per-pair history back to ~1992. The +21 marginal FX-FX events
> revert at much lower rates, dragging the FX-FX average to 24%. The
> implication: the 37% v1 number was specific to the 2010-2026 window. The
> pre-2010 era — different FX regime, different vol structure — does not
> sustain the same qualification edge.
>
> ### What this means for downstream work
>
> 1. **The deferred β-weighted COINTREV v1.2 strategy build should NOT target
>    the 37% reversion rate as its edge assumption.** A realistic target is
>    ≤25%, baseline-consistent — meaning a β-weighted strategy must extract
>    its edge from sources OTHER than qualification (e.g., hedge-ratio
>    construction itself, exit timing, position sizing). If a backtest of a
>    β-weighted strategy on these events shows reversion approaching 37%, it
>    is almost certainly fitting noise specific to one window.
>
> 2. **The screener's infra remains correct** — ADF and OLS on per-pair
>    spreads continue to do clean math. The screener identifies relationships
>    that statistically test cointegrated; whether those relationships have
>    operational edge after qualification is a separate question that v2
>    answers negatively at the universe level.
>
> 3. **Cross-asset cointegration is plausibly real but under-powered to
>    confirm.** 8 events at τ=2.0 reverting at 50% is too small to lean on.
>    The screener's most-cointegrated cross-asset pairs (BTCUSD/NZDJPY,
>    GBPJPY/XAUUSD, EURJPY/XAUUSD per 2026-05-21 entry) warrant per-pair
>    sanity checks before any strategy build, not blanket inclusion.
>
> ### Caveats preserved from v1 (still apply)
>
> - Monthly ADF sampling (every 21 bars) — qualification can be off by up to
>   21 days on either side of a true regime transition.
> - In-sample β and z-score windows — no out-of-sample hedge ratio validation.
> - 60-bar forward window is arbitrary — longer windows would raise both
>   reversion rate and mean-time-to-reversion proportionally.
> - `qual_break_rate` 95-100% across thresholds — qualification almost always
>   degrades during the forward window; the entry shock IS the regime shock.
> - Per-pair history start dates differ; comparing reversion rates across
>   different vintages is not strictly apples-to-apples.
>
> ### v1 archive
>
> The original 18-FX inner-join report is preserved at
> [`EVENT_STUDY_REPORT_v1_18fx_inner.md`](EVENT_STUDY_REPORT_v1_18fx_inner.md)
> including its own caveat block from the 2026-05-21 COINTREV retirement.
>
> ---

# Cointegration Event Study — Concept Validation (v2, 2026-05-23)

**Generated:** 2026-05-23T04:23:55.432122+00:00  
**Spec reference:** [`COINTEGRATION_SCREENER_V1_SPEC.md`](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)

## Hypothesis under test

> Do structurally persistent FX relationships (cointegrated in BOTH 252d and 504d windows, qualification held as-of event) exhibit reliable forward mean-reversion after abnormal spread displacement, before structural regime degradation?

## Methodology

- **Universe:** 21 symbols (AUDUSD, EURUSD, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY, AUDJPY, AUDNZD, CADJPY, CHFJPY, EURAUD, EURGBP, EURJPY, GBPAUD, GBPJPY, GBPNZD, NZDJPY, XAUUSD, BTCUSD, ETHUSD), 210 unordered pair-pairs
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

- Qualified-cohort events: **275** across all thresholds + pairs
- All-cohort events:        **13,554** (baseline)
- Filter retention:         **2.0%** (cointegration qualification removes 98.0% of events)

## Summary by threshold — QUALIFIED cohort

|   threshold |   n_events |   reversion_rate |   median_bars_to_reversion |   median_max_z_in_window |   median_adverse_excursion |   p90_adverse_excursion |   qual_break_rate |
|------------:|-----------:|-----------------:|---------------------------:|-------------------------:|---------------------------:|------------------------:|------------------:|
|         1.5 |        116 |            0.267 |                       36   |                    2.678 |                      1.138 |                   2.462 |             0.957 |
|         2   |         83 |            0.265 |                       39   |                    2.947 |                      0.859 |                   2.133 |             0.964 |
|         2.5 |         57 |            0.211 |                       35   |                    3.143 |                      0.602 |                   1.713 |             1     |
|         3   |         19 |            0.211 |                       38.5 |                    3.966 |                      0.797 |                   1.404 |             1     |

## Summary by threshold — ALL (baseline) cohort

|   threshold |   n_events |   reversion_rate |   median_bars_to_reversion |   median_max_z_in_window |   median_adverse_excursion |   p90_adverse_excursion |   qual_break_rate |
|------------:|-----------:|-----------------:|---------------------------:|-------------------------:|---------------------------:|------------------------:|------------------:|
|         1.5 |       5498 |            0.365 |                         34 |                    2.216 |                      0.673 |                   1.967 |                 0 |
|         2   |       4097 |            0.284 |                         40 |                    2.546 |                      0.505 |                   1.661 |                 0 |
|         2.5 |       2553 |            0.259 |                         42 |                    2.979 |                      0.414 |                   1.441 |                 0 |
|         3   |       1406 |            0.245 |                         42 |                    3.414 |                      0.353 |                   1.273 |                 0 |

## Reversion lift over baseline

|   threshold |   qualified_reversion_rate |   baseline_reversion_rate |   lift_percentage_points |
|------------:|---------------------------:|--------------------------:|-------------------------:|
|         1.5 |                      0.267 |                     0.365 |                   -9.798 |
|         2   |                      0.265 |                     0.284 |                   -1.856 |
|         2.5 |                      0.211 |                     0.259 |                   -4.799 |
|         3   |                      0.211 |                     0.245 |                   -3.485 |

## Interpretation

- **Suggested threshold (qualified cohort):** τ = **2.0**
  - reversion rate 26.5% over 83 events
  - median bars-to-reversion 39
  - p90 adverse excursion 2.13 z-units past entry

- **Caveats:**
  - In-sample β and z-score windows — no out-of-sample validation of the hedge ratio
  - Monthly ADF sampling — qualification could be over/under-stated by up to 21 days
  - 60-bar forward window is arbitrary — longer windows would raise reversion rate AND mean-time-to-reversion
  - No trading-cost model — z-score reversion ≠ tradable P/L
  - Failure-mode skew: pairs that broke during the forward window are counted in `qual_break_rate`

## Files

- `event_summary_by_threshold.csv` — the summary tables above as CSV
- `events_detail.parquet` — every event as a row (cohort, pair, ts, threshold, all stats) for any follow-up slicing (per-pair, per-year, per-direction, etc.)
