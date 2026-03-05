# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10 / NO_THROTTLE_CAP_6

Engine: Robustness v2.1.1 | Generated: 2026-03-03 14:47:45

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2893 |
| Win Rate | 55.4% |
| Avg Win | $48.10 |
| Avg Loss | $54.41 |
| Payoff Ratio | 0.88 |
| Expectancy / Trade | $2.42 |
| Profit Factor | 1.11 |
| Net Profit | $7,338.25 |
| Max DD (USD) | $2,552.10 |
| Recovery Factor | 2.88 |

## Section 2 — Tail Contribution

- Top 1 trade: 6.64%
- Top 5 trades: 26.51%
- Top 1% (28): 94.33%
- Top 5% (144): 312.16%
- Total PnL: $7,338.25

## Section 3 — Tail Removal

**Removing Top 1% (28 trades)**
- Original CAGR: 50.33%
- New CAGR: 3.07%
- Degradation: 93.91%
- New Equity: $10,416.22

**Removing Top 5% (144 trades)**
- Original CAGR: 50.33%
- New CAGR: -100.00%
- Degradation: 298.70%
- New Equity: $-5,568.54

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.52%
- Median CAGR: 0.52%
- 5th pctl CAGR: 0.52%
- 95th pctl CAGR: 0.52%
- Mean DD: 16.07%
- 95th pctl DD: 22.67%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $17,487.32
- CAGR: 51.17%
- Max DD: 17.05%
- Max Loss Streak: 16

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 4
- DD > 20%: 0
- Worst return: 25.81%
- Worst DD: 15.36%
- Mean return: 32.83%
- Mean DD: 14.89%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 564 | $2,748.06 | 55.1% | $4.87 |
| 2025 | 2095 | $4,704.14 | 55.9% | $2.25 |
| 2026 | 234 | $-113.95 | 52.1% | $-0.49 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +504 | +1468 | +776 |
| 2025 | +519 | -710 | +629 | +953 | -712 | +1774 | -50 | +231 | -184 | -389 | +601 | +2041 |
| 2026 | -230 | +116 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-08-07
- Trough: 2025-10-22
- Recovery: 2025-12-15
- Max DD: 15.36%
- Duration: 130 days
- Trades open: 404
- Long/Short: 52.7% / 47.3%
- Top-2 symbol concentration: 34.4%
- Trades closed in plunge: 402
- Win rate: 56.0%
- Avg PnL: $-5.38
- Max loss streak: 7

### Cluster 2
- Start: 2025-02-14
- Trough: 2025-03-07
- Recovery: 2025-04-22
- Max DD: 11.25%
- Duration: 67 days
- Trades open: 164
- Long/Short: 50.0% / 50.0%
- Top-2 symbol concentration: 41.5%
- Trades closed in plunge: 162
- Win rate: 43.8%
- Avg PnL: $-7.00
- Max loss streak: 16

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
| Max Streak | 16 | 16 |
| Avg Streak | 2.5 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $7,338.25 | 1.11 | 0.00% |
| Slip 1.0 pip RT | $-5,973.45 | 0.92 | 181.40% |
| Spread +50% | $-4,835.67 | 0.94 | 165.90% |
| Severe (1.0 + 75%) | $-24,234.33 | 0.72 | 430.25% |

## Section 10 — Directional Robustness

- Total Longs: 1517
- Total Shorts: 1376
- Baseline PF: 1.11
- No Top-20 Longs PF: 1.03
- No Top-20 Shorts PF: 1.05
- No Both PF: 0.98

## Section 11 — Early/Late Split

**First Half** (1446 trades)
- CAGR: 63.52%
- Max DD: 11.67%
- Win Rate: 54.98%

**Second Half** (1447 trades)
- CAGR: 54.83%
- Max DD: 21.83%
- Win Rate: 55.91%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 2491 | 33.08% | 20.62% |
| AUDUSD | 2465 | 38.93% | 19.72% |
| EURUSD | 2489 | 44.58% | 13.88% |
| GBPNZD | 2527 | 42.12% | 18.78% |
| GBPUSD | 2438 | 47.16% | 13.72% |
| USDCHF | 2478 | 48.47% | 16.41% |
| USDJPY | 2470 | 49.52% | 13.06% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDNZD | 402 | $2,620.11 | 60.9% | +35.7% |
| AUDUSD | 428 | $1,737.88 | 54.4% | +23.7% |
| GBPNZD | 366 | $1,251.37 | 57.1% | +17.1% |
| EURUSD | 404 | $874.15 | 53.0% | +11.9% |
| GBPUSD | 455 | $474.90 | 53.8% | +6.5% |
| USDCHF | 415 | $271.90 | 54.9% | +3.7% |
| USDJPY | 423 | $107.94 | 54.4% | +1.5% |

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
- Kruskal-Wallis H: 10.45
- Kruskal-Wallis p-value: 0.4904
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 347 | $289.57 | 1.03 | — |
| 2 | 257 | $-593.88 | 0.90 | — |
| 3 | 202 | $628.58 | 1.15 | — |
| 4 | 212 | $952.67 | 1.20 | — |
| 5 | 148 | $-711.85 | 0.82 | — |
| 6 | 155 | $1,773.89 | 1.65 | — |
| 7 | 218 | $-49.79 | 0.99 | — |
| 8 | 143 | $230.69 | 1.05 | — |
| 9 | 158 | $-183.57 | 0.96 | — |
| 10 | 402 | $115.32 | 1.01 | — |
| 11 | 343 | $2,069.39 | 1.29 | — |
| 12 | 308 | $2,817.23 | 1.41 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 5.25 from global mean 2.54
