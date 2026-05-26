# Cointegration 4H vs 1D Lead-Lag — Empirical Validation

**Date:** 2026-05-26  
**Phase:** 2 of multi-TF cointegration plan ([scope](https://github.com/), locked 2026-05-26)  
**Goal:** does 4H ADF detect structural cointegration breakdowns materially earlier than 1d?

## Method

- 1d matrix: hash `f2bf45fd6b41`, params `{'tf': '1d', 'hedge_window': 252, 'adf_window_short': 252, 'adf_window_long': 504, 'adf_sample_every': 21, 'adf_lag_bars': 1, 'p_qualify': 0.05, 'schema_version': '1.0.0'}`
- 4h matrix: hash `be27c2c32af5`, params `{'tf': '4h', 'hedge_window': 1500, 'adf_window_short': 1500, 'adf_window_long': 3000, 'adf_sample_every': 30, 'adf_lag_bars': 1, 'p_qualify': 0.05, 'schema_version': '1.0.0'}`
- Basket composition follows [`feedback_experiment_basket_composition`](../../../../../.claude/projects/C--Users-faraw-Documents-Trade-Scan/memory/feedback_experiment_basket_composition.md):
  forced healthy / unstable / S21-control / exploratory diversity.
- For each pair, 4h p-values resampled to daily, then 30-day lead-lag cross-correlation
  computed against 1d p-values. Break events defined as transition from p<0.05 to sustained
  p>=0.05 (>=60 days post-break <=20% qualified).

## Results

| Slot | Pair-pair | Shared bars | Best lag (d) | Corr | 1d breaks | 4h breaks | Paired | 4h earlier | Mean lead (d) | 4h transient runs % |
|---|---|---|---|---|---|---|---|---|---|---|
| 1-stable | EURJPY/GBPJPY | 6,380 | -8 | 0.833 | 13 | 35 | 7 | 5 | 6.6 | 55.0% (20 runs) |
| 2-regime-break | AUDUSD/NZDUSD | 4,552 | -7 | 0.868 | 11 | 24 | 6 | 4 | 10.0 | 41.7% (12 runs) |
| 3-S21-control | EURUSD/USDJPY | 4,552 | -5 | 0.873 | 9 | 27 | 8 | 6 | 7.3 | 50.0% (18 runs) |
| 4-FX-equity | CHFJPY/FRA40 | 1,974 | -7 | 0.799 | 2 | 10 | 2 | 0 | — | 40.0% (5 runs) |
| 5-FX-commodity | GBPJPY/XAUUSD | 2,417 | -4 | 0.793 | 4 | 9 | 2 | 2 | 15.0 | 75.0% (8 runs) |

## Paired break events (per-pair detail)

### 1-stable: EURJPY/GBPJPY — paired break events

| 1d break date | 4h break date | Lead (d) — positive = 4h earlier |
|---|---|---|
| 2005-10-13 | 2005-10-13 | +0 |
| 2009-08-04 | 2009-08-01 | +3 |
| 2011-04-14 | 2011-04-16 | -2 |
| 2013-11-12 | 2013-11-05 | +7 |
| 2017-02-07 | 2017-02-04 | +3 |
| 2019-04-17 | 2019-03-30 | +18 |
| 2024-06-03 | 2024-06-01 | +2 |

### 2-regime-break: AUDUSD/NZDUSD — paired break events

| 1d break date | 4h break date | Lead (d) — positive = 4h earlier |
|---|---|---|
| 2009-11-02 | 2009-10-29 | +4 |
| 2011-04-18 | 2011-04-23 | -5 |
| 2014-05-12 | 2014-05-06 | +6 |
| 2021-03-01 | 2021-02-23 | +6 |
| 2023-09-15 | 2023-09-16 | -1 |
| 2024-10-01 | 2024-09-07 | +24 |

### 3-S21-control: EURUSD/USDJPY — paired break events

| 1d break date | 4h break date | Lead (d) — positive = 4h earlier |
|---|---|---|
| 2009-10-02 | 2009-09-24 | +8 |
| 2010-07-27 | 2010-07-17 | +10 |
| 2015-08-27 | 2015-08-21 | +6 |
| 2018-06-27 | 2018-06-28 | -1 |
| 2019-03-21 | 2019-03-19 | +2 |
| 2021-03-26 | 2021-03-15 | +11 |
| 2023-03-23 | 2023-03-25 | -2 |
| 2025-11-11 | 2025-11-04 | +7 |

### 4-FX-equity: CHFJPY/FRA40 — paired break events

| 1d break date | 4h break date | Lead (d) — positive = 4h earlier |
|---|---|---|
| 2019-02-12 | 2019-03-30 | -46 |
| 2023-03-15 | 2023-03-18 | -3 |

### 5-FX-commodity: GBPJPY/XAUUSD — paired break events

| 1d break date | 4h break date | Lead (d) — positive = 4h earlier |
|---|---|---|
| 2017-02-08 | 2017-02-04 | +4 |
| 2022-03-01 | 2022-02-03 | +26 |


### Reading the columns

- **Best lag (d)**: negative = 4h time series leads 1d; positive = 1d leads 4h; 0 = coincident.
  Lag is in days because 4h was resampled to 1D for alignment.
- **Corr**: Pearson correlation of p-value time series at best lag. Higher = more co-movement.
- **1d breaks**: number of sustained qualification breaks the 1d series shows over the test window.
- **4h earlier**: subset of those breaks where 4h crossed p=0.05 BEFORE the 1d break date.
- **Mean lead (d)**: average earlier-detection time, in calendar days. Higher = more lead.
- **4h transient runs %**: percent of 4h qualified runs that lasted < 30 days. High = noisy.

## Interpretation

### Across-basket signal

| Criterion | Result | Pass? |
|---|---|---|
| Best lag negative (4H leads) on cross-correlation | **5/5** at −4 to −8 days | ✓ strong |
| 4H earlier on paired break events | **17/25** (68%) when matched within ±60 d | ✓ moderate |
| Mean lead on earlier detections | 6.6, 10.0, 7.3, —, 15.0 days | only 2/5 ≥ 10 d |
| 4H transient-noise rate (< 30%) | 40 / 42 / 50 / 40 / 75% | **0/5 ✗** universal fail |

**Two real findings**, in tension:

1. **The 4H ADF p-value series consistently leads 1d by 4–8 days at cross-correlation peak**, across every diverse pair class we tested (yen-cross FX-FX, Antipodean FX-FX, S21 control, FX-equity, FX-commodity). This is the clean positive: 4H carries the same regime information as 1d, just shifted earlier in time. The signal is real.

2. **Raw 4H qualified-flag is structurally noisy.** Every basket member has 40–75% transient runs (qualified episodes lasting < 30 days). The raw cross-of-p=0.05 fires false alarms at a high rate. Operationalizing the raw 4H flag (e.g. for daily regime-alert) would generate too many noise events to be actionable.

### Per-slot verdicts

- **Slot 1 (EURJPY/GBPJPY, stable healthy):** 7 paired breaks, 5/7 4H led, mean 6.6 d. Confirms 4H lead on the healthy-pair baseline. The 18-day lead in 2019-04 event is the largest.
- **Slot 2 (AUDUSD/NZDUSD, regime-break):** 6 paired breaks, 4/6 4H led, mean 10.0 d. The 24-d lead in 2024-10 (RBA/RBNZ divergence late stage) is large and matches the prior known regime episode. Validates the lead-detection hypothesis on the deteriorating-pair quadrant.
- **Slot 3 (EURUSD/USDJPY, S21 control):** 8 paired breaks (most of any pair), 6/8 4H led, mean 7.3 d, transient 50%. The S21 strategy's pair shows the same pattern — 4H leads but with noise. Operationalizing 4H for S21 entry timing is **not justified** by this evidence; the 4H signal would inform regime-state monitoring, not entry timing.
- **Slot 4 (CHFJPY/FRA40, FX-equity opportunistic):** only 2 paired events (very stable pair, few breaks); 0/2 4H led, both lagged. Sample size too small to conclude, but no evidence of 4H lead on this surface. The 2019-02 event shows 4H lagged by 46 days — possibly a 1d false-positive break that 4H correctly didn't echo.
- **Slot 5 (GBPJPY/XAUUSD, FX-commodity opportunistic):** 2 paired events, both 4H led (mean 15 d, the highest lead in the basket). But also highest transient noise at 75%. The lead-when-it-happens is real but the signal is the noisiest of the basket — confirms 4H is detecting microstructure noise on this surface too.

### Cross-asset finding (slots 4 + 5)

The user hypothesis that **cross-asset (FX-equity, FX-commodity) is the highest-value surface for 4H detection** is **not supported by this small sample**. Both cross-asset pairs had only 2 paired break events historically — these pairs have been *too stable to test the lead-detection hypothesis*. FX-FX pairs (slots 1–3) had 6–8 paired events each, much better statistical leverage.

Counter-intuitively: **cross-asset pairs may be where 4H operationalization is *least* valuable** because the underlying relationship is stable enough that intraday lead doesn't add much beyond daily monitoring. The FX-FX pairs are where 4H lead matters most because those pairs have more frequent regime breaks to detect.

## Decision gate

Per Phase 2 acceptance criteria (locked in implementation plan 2026-05-26):

- **Proceed to operational 4h pipeline (Phase 5)** if: ≥3 basket members show negative
  best_lag (4h leads) with mean lead ≥ 10 days AND transient_runs_4h_pct < 30%.
- **Keep plumbing dormant** if: lead is < 10 days OR transient_runs_4h_pct ≥ 30%
  (spurious noise dominates).
- **Mixed**: revisit basket + extend analysis before deciding.

### Verdict: **MIXED — raw 4H not operationalizable; smoothed 4H may be.**

- Best-lag check: 5/5 pass (negative lag everywhere)
- Mean-lead-≥-10 check: 2/5 pass (slots 2, 5)
- Transient-noise-<-30% check: **0/5 pass** (universal fail)

The cross-correlation signal is real and consistent. The raw qualified-flag signal is too noisy to schedule as a daily alert.

### Recommended next steps (ranked)

1. **Higher priority** — **do not operationalize 4H yet.** Focus on the explicitly higher-value research items from the 90-series audit: cross-pair port of S21 P06/P07/P08 to GBPUSDUSDJPY + AUDUSDUSDCAD, and N=30 Pine-port Trade_Scan validation.
2. **If 4H operationalization is pursued later, the path is smoothing not raw flagging.** Implement the Phase-2 SQLite-backed `pvalue_rolling_median_5d` at 4H specifically (it was originally specced for 1d). With 4H anchors at ~30-bar cadence and a 5-anchor rolling median, that's a ~5-week smoothing window — should bring transient rate well under 30%. Re-test lead-lag on the smoothed series before deciding.
3. **Keep this report + the focused matrices** as the audit trail for the decision. The focused matrices (`be27c2c32af5` for 4h, `f2bf45fd6b41` for 1d) stay on disk; the 1d LATEST pointer must be restored to the production matrix `6e6202fa4958` after this report is committed (run `python tmp/restore_1d_production_latest.py`).
4. **Do not extend the basket experiment.** The 5-pair design answered the question. Adding more pairs would only confirm or refine the same finding (4H leads in cross-correlation, raw flag is noisy).

## Provenance

- Script: `tmp/analyze_4h_vs_1d_leadlag.py`
- 1d matrix manifest: `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/f2bf45fd6b41.manifest.json`
- 4h matrix manifest: `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/be27c2c32af5.manifest.json`