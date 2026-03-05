# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10 / NO_THROTTLE_CAP_7

Engine: Robustness v2.1.1 | Generated: 2026-03-03 14:50:15

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2897 |
| Win Rate | 55.4% |
| Avg Win | $48.64 |
| Avg Loss | $54.89 |
| Payoff Ratio | 0.89 |
| Expectancy / Trade | $2.51 |
| Profit Factor | 1.11 |
| Net Profit | $7,593.70 |
| Max DD (USD) | $2,592.72 |
| Recovery Factor | 2.93 |

## Section 2 — Tail Contribution

- Top 1 trade: 6.60%
- Top 5 trades: 26.04%
- Top 1% (28): 92.71%
- Top 5% (144): 306.25%
- Total PnL: $7,593.70

## Section 3 — Tail Removal

**Removing Top 1% (28 trades)**
- Original CAGR: 51.97%
- New CAGR: 4.07%
- Degradation: 92.17%
- New Equity: $10,553.23

**Removing Top 5% (144 trades)**
- Original CAGR: 51.97%
- New CAGR: -100.00%
- Degradation: 292.43%
- New Equity: $-5,661.86

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.54%
- Median CAGR: 0.54%
- 5th pctl CAGR: 0.53%
- 95th pctl CAGR: 0.54%
- Mean DD: 16.15%
- 95th pctl DD: 24.05%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $17,720.31
- CAGR: 52.66%
- Max DD: 17.17%
- Max Loss Streak: 15

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 4
- DD > 20%: 0
- Worst return: 27.50%
- Worst DD: 15.38%
- Mean return: 34.66%
- Mean DD: 14.88%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 566 | $2,770.19 | 55.1% | $4.89 |
| 2025 | 2097 | $4,941.60 | 55.9% | $2.36 |
| 2026 | 234 | $-118.09 | 52.1% | $-0.50 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +501 | +1486 | +783 |
| 2025 | +518 | -717 | +626 | +1157 | -738 | +1806 | -44 | +236 | -172 | -421 | +600 | +2090 |
| 2026 | -233 | +115 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-08-07
- Trough: 2025-10-22
- Recovery: 2025-12-15
- Max DD: 15.38%
- Duration: 130 days
- Trades open: 404
- Long/Short: 52.7% / 47.3%
- Top-2 symbol concentration: 34.4%
- Trades closed in plunge: 402
- Win rate: 56.0%
- Avg PnL: $-5.46
- Max loss streak: 7

### Cluster 2
- Start: 2025-02-14
- Trough: 2025-03-07
- Recovery: 2025-04-22
- Max DD: 11.26%
- Duration: 67 days
- Trades open: 164
- Long/Short: 50.0% / 50.0%
- Top-2 symbol concentration: 41.5%
- Trades closed in plunge: 162
- Win rate: 43.8%
- Avg PnL: $-7.01
- Max loss streak: 15

### Cluster 3
- Start: 2024-10-21
- Trough: 2024-10-31
- Recovery: 2024-11-07
- Max DD: 7.12%
- Duration: 17 days
- Trades open: 79
- Long/Short: 48.1% / 51.9%
- Top-2 symbol concentration: 45.6%
- Trades closed in plunge: 78
- Win rate: 44.9%
- Avg PnL: $-10.12
- Max loss streak: 8

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 16 | 15 |
| Avg Streak | 2.5 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $7,593.70 | 1.11 | 0.00% |
| Slip 1.0 pip RT | $-5,859.00 | 0.92 | 177.16% |
| Spread +50% | $-4,707.14 | 0.94 | 161.99% |
| Severe (1.0 + 75%) | $-24,310.25 | 0.72 | 420.14% |

## Section 10 — Directional Robustness

- Total Longs: 1520
- Total Shorts: 1377
- Baseline PF: 1.11
- No Top-20 Longs PF: 1.04
- No Top-20 Shorts PF: 1.05
- No Both PF: 0.98

## Section 11 — Early/Late Split

**First Half** (1448 trades)
- CAGR: 69.31%
- Max DD: 11.69%
- Win Rate: 55.04%

**Second Half** (1449 trades)
- CAGR: 54.28%
- Max DD: 22.22%
- Win Rate: 55.83%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 2495 | 34.55% | 20.71% |
| AUDUSD | 2469 | 40.54% | 19.78% |
| EURUSD | 2493 | 46.13% | 13.80% |
| GBPNZD | 2531 | 43.86% | 18.77% |
| GBPUSD | 2441 | 48.86% | 13.76% |
| USDCHF | 2482 | 50.12% | 16.40% |
| USDJPY | 2471 | 49.77% | 13.08% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDNZD | 402 | $2,655.10 | 60.9% | +35.0% |
| AUDUSD | 428 | $1,747.76 | 54.4% | +23.0% |
| GBPNZD | 366 | $1,239.46 | 57.1% | +16.3% |
| EURUSD | 404 | $889.96 | 53.0% | +11.7% |
| GBPUSD | 456 | $466.41 | 53.7% | +6.1% |
| USDJPY | 426 | $325.20 | 54.5% | +4.3% |
| USDCHF | 415 | $269.81 | 54.9% | +3.6% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 3.04%
- Median CAGR: 1.36%
- 5th pctl CAGR: -2.58%
- 95th pctl CAGR: 13.80%
- Mean DD: 12.02%
- Worst DD: 19.26%
- Runs ending below start: 76

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 10.57
- Kruskal-Wallis p-value: 0.4800
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 347 | $284.44 | 1.03 | — |
| 2 | 257 | $-601.73 | 0.90 | — |
| 3 | 202 | $626.34 | 1.15 | — |
| 4 | 214 | $1,157.28 | 1.24 | — |
| 5 | 148 | $-737.98 | 0.82 | — |
| 6 | 155 | $1,805.78 | 1.65 | — |
| 7 | 218 | $-44.24 | 0.99 | — |
| 8 | 143 | $235.88 | 1.05 | — |
| 9 | 158 | $-171.65 | 0.96 | — |
| 10 | 403 | $79.63 | 1.01 | — |
| 11 | 344 | $2,086.06 | 1.29 | — |
| 12 | 308 | $2,873.89 | 1.42 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 4.99 from global mean 2.62
