# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10 / AGGRESSIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-03-03 14:13:15

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 475 |
| Win Rate | 53.3% |
| Avg Win | $61.58 |
| Avg Loss | $67.00 |
| Payoff Ratio | 0.92 |
| Expectancy / Trade | $1.48 |
| Profit Factor | 1.05 |
| Net Profit | $772.08 |
| Max DD (USD) | $1,239.17 |
| Recovery Factor | 0.62 |

## Section 2 — Tail Contribution

- Top 1 trade: 41.46%
- Top 5 trades: 170.31%
- Top 1% (4): 141.75%
- Top 5% (23): 561.35%
- Total PnL: $772.08

## Section 3 — Tail Removal

**Removing Top 1% (4 trades)**
- Original CAGR: 5.66%
- New CAGR: -2.40%
- Degradation: 142.34%
- New Equity: $9,677.65

**Removing Top 5% (23 trades)**
- Original CAGR: 5.66%
- New CAGR: -27.83%
- Degradation: 591.44%
- New Equity: $6,438.04

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.06%
- Median CAGR: 0.06%
- 5th pctl CAGR: 0.06%
- 95th pctl CAGR: 0.06%
- Mean DD: 16.74%
- 95th pctl DD: 23.02%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $10,775.66
- CAGR: 5.68%
- Max DD: 12.85%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 5.35%
- Worst DD: 12.40%
- Mean return: 10.46%
- Mean DD: 11.88%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 89 | $-454.61 | 48.3% | $-5.11 |
| 2025 | 355 | $1,306.04 | 54.9% | $3.68 |
| 2026 | 31 | $-79.35 | 48.4% | $-2.56 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | -417 | +93 | -131 |
| 2025 | +267 | -306 | -95 | -105 | +376 | +587 | +101 | +119 | +130 | +88 | +29 | +115 |
| 2026 | +278 | -357 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-11-08
- Trough: 2025-04-17
- Recovery: 2025-06-23
- Max DD: 12.40%
- Duration: 227 days
- Trades open: 212
- Long/Short: 51.4% / 48.6%
- Top-2 symbol concentration: 69.3%
- Trades closed in plunge: 212
- Win rate: 50.9%
- Avg PnL: $-4.71
- Max loss streak: 6

### Cluster 2
- Start: 2026-01-22
- Trough: 2026-02-06
- Recovery: ONGOING
- Max DD: 8.35%
- Duration: 22 days
- Trades open: 20
- Long/Short: 40.0% / 60.0%
- Top-2 symbol concentration: 70.0%
- Trades closed in plunge: 19
- Win rate: 31.6%
- Avg PnL: $-46.46
- Max loss streak: 6

### Cluster 3
- Start: 2025-07-15
- Trough: 2025-10-09
- Recovery: 2026-01-05
- Max DD: 7.27%
- Duration: 174 days
- Trades open: 49
- Long/Short: 44.9% / 55.1%
- Top-2 symbol concentration: 79.6%
- Trades closed in plunge: 49
- Win rate: 53.1%
- Avg PnL: $-13.06
- Max loss streak: 4

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 6 |
| Avg Streak | 2.0 | 1.8 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $772.08 | 1.05 | 0.00% |
| Slip 1.0 pip RT | $-1,622.32 | 0.90 | 310.12% |
| Spread +50% | $-761.90 | 0.95 | 198.68% |
| Severe (1.0 + 75%) | $-3,923.30 | 0.77 | 608.15% |

## Section 10 — Directional Robustness

- Total Longs: 235
- Total Shorts: 240
- Baseline PF: 1.05
- No Top-20 Longs PF: 0.87
- No Top-20 Shorts PF: 0.81
- No Both PF: 0.62

## Section 11 — Early/Late Split

**First Half** (237 trades)
- CAGR: -19.76%
- Max DD: 11.49%
- Win Rate: 49.79%

**Second Half** (238 trades)
- CAGR: 22.83%
- Max DD: 8.20%
- Win Rate: 56.72%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 474 | 5.71% | 12.79% |
| AUDUSD | 247 | 3.38% | 6.93% |
| EURUSD | 411 | 3.17% | 14.41% |
| GBPUSD | 421 | 7.53% | 10.37% |
| USDCHF | 347 | 2.84% | 10.45% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 128 | $385.74 | 53.9% | +50.0% |
| EURUSD | 64 | $340.76 | 59.4% | +44.1% |
| AUDUSD | 228 | $313.08 | 52.2% | +40.6% |
| AUDNZD | 1 | $-7.26 | 0.0% | -0.9% |
| GBPUSD | 54 | $-260.24 | 50.0% | -33.7% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 1.32%
- Median CAGR: 1.42%
- 5th pctl CAGR: -3.37%
- 95th pctl CAGR: 5.24%
- Mean DD: 6.28%
- Worst DD: 8.04%
- Runs ending below start: 33

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 3.75
- Kruskal-Wallis p-value: 0.9766
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 55 | $544.91 | 1.41 | — |
| 2 | 42 | $-663.18 | 0.60 | — |
| 3 | 36 | $-95.22 | 0.91 | — |
| 4 | 68 | $-105.23 | 0.95 | — |
| 5 | 39 | $375.89 | 1.35 | — |
| 6 | 41 | $587.01 | 1.60 | — |
| 7 | 31 | $100.82 | 1.09 | — |
| 8 | 9 | $119.28 | 1.56 | — |
| 9 | 15 | $130.01 | 1.45 | — |
| 10 | 43 | $-328.95 | 0.81 | — |
| 11 | 63 | $121.96 | 1.06 | — |
| 12 | 33 | $-15.22 | 0.99 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 8.78 from global mean 1.63
