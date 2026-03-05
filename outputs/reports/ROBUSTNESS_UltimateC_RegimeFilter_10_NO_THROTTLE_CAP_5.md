# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10 / NO_THROTTLE_CAP_5

Engine: Robustness v2.1.1 | Generated: 2026-03-03 14:45:18

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2866 |
| Win Rate | 55.3% |
| Avg Win | $46.70 |
| Avg Loss | $52.84 |
| Payoff Ratio | 0.88 |
| Expectancy / Trade | $2.21 |
| Profit Factor | 1.10 |
| Net Profit | $6,650.66 |
| Max DD (USD) | $2,633.53 |
| Recovery Factor | 2.53 |

## Section 2 — Tail Contribution

- Top 1 trade: 7.12%
- Top 5 trades: 28.53%
- Top 1% (28): 101.33%
- Top 5% (143): 332.44%
- Total PnL: $6,650.66

## Section 3 — Tail Removal

**Removing Top 1% (28 trades)**
- Original CAGR: 45.89%
- New CAGR: -0.66%
- Degradation: 101.43%
- New Equity: $9,911.54

**Removing Top 5% (143 trades)**
- Original CAGR: 45.89%
- New CAGR: -100.00%
- Degradation: 317.92%
- New Equity: $-5,458.59

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.47%
- Median CAGR: 0.47%
- 5th pctl CAGR: 0.47%
- 95th pctl CAGR: 0.48%
- Mean DD: 16.64%
- 95th pctl DD: 23.62%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $16,812.08
- CAGR: 46.83%
- Max DD: 18.00%
- Max Loss Streak: 15

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 4
- DD > 20%: 0
- Worst return: 22.47%
- Worst DD: 16.31%
- Mean return: 29.36%
- Mean DD: 15.63%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 558 | $2,540.53 | 55.0% | $4.55 |
| 2025 | 2074 | $4,210.56 | 55.7% | $2.03 |
| 2026 | 234 | $-100.43 | 52.1% | $-0.43 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +413 | +1349 | +779 |
| 2025 | +553 | -772 | +466 | +666 | -452 | +1718 | +6 | +227 | -170 | -554 | +575 | +1947 |
| 2026 | -214 | +113 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-08-07
- Trough: 2025-10-22
- Recovery: 2025-12-18
- Max DD: 16.31%
- Duration: 133 days
- Trades open: 401
- Long/Short: 52.6% / 47.4%
- Top-2 symbol concentration: 34.4%
- Trades closed in plunge: 399
- Win rate: 55.6%
- Avg PnL: $-5.65
- Max loss streak: 7

### Cluster 2
- Start: 2025-02-14
- Trough: 2025-03-07
- Recovery: 2025-04-25
- Max DD: 11.97%
- Duration: 70 days
- Trades open: 162
- Long/Short: 50.0% / 50.0%
- Top-2 symbol concentration: 41.4%
- Trades closed in plunge: 160
- Win rate: 43.1%
- Avg PnL: $-7.63
- Max loss streak: 15

### Cluster 3
- Start: 2024-11-08
- Trough: 2024-11-13
- Recovery: 2024-11-27
- Max DD: 7.32%
- Duration: 19 days
- Trades open: 49
- Long/Short: 36.7% / 63.3%
- Top-2 symbol concentration: 34.7%
- Trades closed in plunge: 47
- Win rate: 38.3%
- Avg PnL: $-11.10
- Max loss streak: 8

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 16 | 15 |
| Avg Streak | 2.5 | 2.1 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $6,650.66 | 1.10 | 0.00% |
| Slip 1.0 pip RT | $-6,195.34 | 0.92 | 193.15% |
| Spread +50% | $-5,107.83 | 0.93 | 176.80% |
| Severe (1.0 + 75%) | $-23,833.07 | 0.71 | 458.36% |

## Section 10 — Directional Robustness

- Total Longs: 1502
- Total Shorts: 1364
- Baseline PF: 1.10
- No Top-20 Longs PF: 1.03
- No Top-20 Shorts PF: 1.04
- No Both PF: 0.97

## Section 11 — Early/Late Split

**First Half** (1433 trades)
- CAGR: 55.77%
- Max DD: 12.38%
- Win Rate: 54.71%

**Second Half** (1433 trades)
- CAGR: 50.45%
- Max DD: 22.51%
- Win Rate: 55.90%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 2465 | 29.44% | 21.53% |
| AUDUSD | 2440 | 35.23% | 20.62% |
| EURUSD | 2467 | 40.66% | 13.82% |
| GBPNZD | 2503 | 36.82% | 20.00% |
| GBPUSD | 2415 | 41.96% | 14.94% |
| USDCHF | 2456 | 45.66% | 17.14% |
| USDJPY | 2450 | 47.07% | 13.68% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDNZD | 401 | $2,473.61 | 60.8% | +37.2% |
| AUDUSD | 426 | $1,609.21 | 54.2% | +24.2% |
| GBPNZD | 363 | $1,369.76 | 57.3% | +20.6% |
| EURUSD | 399 | $787.18 | 52.9% | +11.8% |
| GBPUSD | 451 | $588.62 | 53.9% | +8.9% |
| USDCHF | 410 | $20.43 | 54.6% | +0.3% |
| USDJPY | 416 | $-198.15 | 53.8% | -3.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 3.16%
- Median CAGR: 2.31%
- 5th pctl CAGR: -3.29%
- 95th pctl CAGR: 13.80%
- Mean DD: 11.69%
- Worst DD: 19.44%
- Runs ending below start: 78

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 9.47
- Kruskal-Wallis p-value: 0.5788
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 346 | $339.60 | 1.04 | — |
| 2 | 256 | $-658.44 | 0.89 | — |
| 3 | 198 | $465.66 | 1.12 | — |
| 4 | 206 | $665.88 | 1.15 | — |
| 5 | 146 | $-451.91 | 0.88 | — |
| 6 | 155 | $1,718.28 | 1.65 | — |
| 7 | 215 | $6.35 | 1.00 | — |
| 8 | 143 | $227.06 | 1.05 | — |
| 9 | 158 | $-169.68 | 0.96 | — |
| 10 | 396 | $-141.79 | 0.99 | — |
| 11 | 340 | $1,923.84 | 1.27 | — |
| 12 | 307 | $2,725.81 | 1.41 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 4.79 from global mean 2.32
