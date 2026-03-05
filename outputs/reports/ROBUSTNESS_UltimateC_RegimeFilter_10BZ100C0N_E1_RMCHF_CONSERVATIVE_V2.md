# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10BZ100C0N_E1_RMCHF / CONSERVATIVE_V2

Engine: Robustness v2.1.1 | Generated: 2026-03-05 08:24:46

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2499 |
| Win Rate | 54.0% |
| Avg Win | $58.09 |
| Avg Loss | $58.84 |
| Payoff Ratio | 0.99 |
| Expectancy / Trade | $4.33 |
| Profit Factor | 1.17 |
| Net Profit | $11,283.54 |
| Max DD (USD) | $1,934.72 |
| Recovery Factor | 5.83 |

## Section 2 — Tail Contribution

- Top 1 trade: 5.10%
- Top 5 trades: 21.64%
- Top 1% (24): 70.24%
- Top 5% (124): 220.38%
- Total PnL: $11,283.54

## Section 3 — Tail Removal

**Removing Top 1% (24 trades)**
- Original CAGR: 71.52%
- New CAGR: 22.98%
- Degradation: 67.87%
- New Equity: $13,358.50

**Removing Top 5% (124 trades)**
- Original CAGR: 71.52%
- New CAGR: -100.00%
- Degradation: 239.82%
- New Equity: $-3,582.84

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.73%
- Median CAGR: 0.73%
- 5th pctl CAGR: 0.73%
- 95th pctl CAGR: 0.74%
- Mean DD: 13.33%
- 95th pctl DD: 19.08%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $21,491.15
- CAGR: 72.78%
- Max DD: 10.03%
- Max Loss Streak: 10

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 44.64%
- Worst DD: 9.66%
- Mean return: 60.54%
- Mean DD: 9.28%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 472 | $2,997.91 | 52.5% | $6.35 |
| 2025 | 1768 | $7,522.90 | 54.5% | $4.26 |
| 2026 | 259 | $762.73 | 53.3% | $2.94 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +251 | +1038 | +1709 |
| 2025 | +956 | +228 | -374 | +1551 | +375 | +464 | -82 | +231 | +828 | +545 | +1032 | +1769 |
| 2026 | -277 | +392 | +648 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-11-17
- Trough: 2025-12-08
- Recovery: 2025-12-18
- Max DD: 9.66%
- Duration: 31 days
- Trades open: 93
- Long/Short: 53.8% / 46.2%
- Top-2 symbol concentration: 44.1%
- Trades closed in plunge: 92
- Win rate: 40.2%
- Avg PnL: $-19.73
- Max loss streak: 5

### Cluster 2
- Start: 2025-08-20
- Trough: 2025-09-18
- Recovery: 2025-10-03
- Max DD: 8.82%
- Duration: 44 days
- Trades open: 125
- Long/Short: 53.6% / 46.4%
- Top-2 symbol concentration: 45.6%
- Trades closed in plunge: 125
- Win rate: 52.0%
- Avg PnL: $-11.53
- Max loss streak: 5

### Cluster 3
- Start: 2024-10-23
- Trough: 2024-10-31
- Recovery: 2024-11-27
- Max DD: 7.67%
- Duration: 35 days
- Trades open: 49
- Long/Short: 53.1% / 46.9%
- Top-2 symbol concentration: 57.1%
- Trades closed in plunge: 47
- Win rate: 40.4%
- Avg PnL: $-16.55
- Max loss streak: 7

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 14 | 10 |
| Avg Streak | 2.4 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $11,283.54 | 1.17 | 0.00% |
| Slip 1.0 pip RT | $-1,645.56 | 0.98 | 114.58% |
| Spread +50% | $-826.47 | 0.99 | 107.32% |
| Severe (1.0 + 75%) | $-19,810.58 | 0.76 | 275.57% |

## Section 10 — Directional Robustness

- Total Longs: 1333
- Total Shorts: 1166
- Baseline PF: 1.17
- No Top-20 Longs PF: 1.07
- No Top-20 Shorts PF: 1.10
- No Both PF: 1.01

## Section 11 — Early/Late Split

**First Half** (1249 trades)
- CAGR: 99.30%
- Max DD: 9.02%
- Win Rate: 52.60%

**Second Half** (1250 trades)
- CAGR: 82.09%
- Max DD: 14.57%
- Win Rate: 55.44%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 2098 | 53.72% | 12.30% |
| AUDUSD | 2062 | 53.29% | 11.51% |
| EURUSD | 2084 | 62.56% | 9.60% |
| GBPNZD | 2128 | 68.11% | 12.24% |
| GBPUSD | 2044 | 64.18% | 10.95% |
| USDJPY | 2079 | 61.55% | 11.20% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDUSD | 437 | $3,105.90 | 53.5% | +27.5% |
| AUDNZD | 401 | $3,033.72 | 58.6% | +26.9% |
| USDJPY | 420 | $1,720.82 | 51.0% | +15.3% |
| EURUSD | 415 | $1,548.93 | 52.0% | +13.7% |
| GBPUSD | 455 | $1,273.16 | 53.2% | +11.3% |
| GBPNZD | 371 | $601.01 | 56.3% | +5.3% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 5.92%
- Median CAGR: 6.07%
- 5th pctl CAGR: 3.23%
- 95th pctl CAGR: 9.13%
- Mean DD: 9.47%
- Worst DD: 12.69%
- Runs ending below start: 81

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 3.92
- Kruskal-Wallis p-value: 0.9721
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 297 | $679.26 | 1.08 | — |
| 2 | 264 | $619.82 | 1.08 | — |
| 3 | 170 | $273.92 | 1.07 | — |
| 4 | 185 | $1,551.06 | 1.33 | — |
| 5 | 123 | $374.63 | 1.11 | — |
| 6 | 130 | $463.58 | 1.15 | — |
| 7 | 191 | $-81.81 | 0.99 | — |
| 8 | 121 | $230.51 | 1.05 | — |
| 9 | 135 | $828.25 | 1.24 | — |
| 10 | 337 | $796.76 | 1.09 | — |
| 11 | 290 | $2,069.69 | 1.29 | — |
| 12 | 256 | $3,477.87 | 1.59 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 6.01 from global mean 4.52
