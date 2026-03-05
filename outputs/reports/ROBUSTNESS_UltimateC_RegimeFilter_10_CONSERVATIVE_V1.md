# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10 / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-03-03 14:14:23

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 1161 |
| Win Rate | 53.1% |
| Avg Win | $34.91 |
| Avg Loss | $38.15 |
| Payoff Ratio | 0.91 |
| Expectancy / Trade | $0.67 |
| Profit Factor | 1.05 |
| Net Profit | $934.13 |
| Max DD (USD) | $1,430.92 |
| Recovery Factor | 0.65 |

## Section 2 — Tail Contribution

- Top 1 trade: 31.86%
- Top 5 trades: 114.80%
- Top 1% (11): 212.15%
- Top 5% (58): 697.49%
- Total PnL: $934.13

## Section 3 — Tail Removal

**Removing Top 1% (11 trades)**
- Original CAGR: 6.84%
- New CAGR: -7.87%
- Degradation: 215.08%
- New Equity: $8,952.39

**Removing Top 5% (58 trades)**
- Original CAGR: 6.84%
- New CAGR: -45.39%
- Degradation: 763.75%
- New Equity: $4,418.64

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.07%
- Median CAGR: 0.07%
- 5th pctl CAGR: 0.07%
- 95th pctl CAGR: 0.07%
- Mean DD: 14.01%
- 95th pctl DD: 19.59%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $10,942.37
- CAGR: 6.89%
- Max DD: 13.33%
- Max Loss Streak: 9

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 1
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -0.84%
- Worst DD: 12.82%
- Mean return: 2.91%
- Mean DD: 11.82%
- Negative clustering: ISOLATED (Only 1)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 220 | $940.36 | 52.7% | $4.27 |
| 2025 | 845 | $86.82 | 53.5% | $0.10 |
| 2026 | 96 | $-93.05 | 51.0% | $-0.97 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | -47 | +282 | +705 |
| 2025 | -311 | -347 | -351 | +194 | -306 | +674 | +36 | +109 | +10 | +101 | +29 | +252 |
| 2026 | -33 | -60 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-12-26
- Trough: 2025-05-29
- Recovery: 2026-01-16
- Max DD: 12.82%
- Duration: 386 days
- Trades open: 444
- Long/Short: 50.7% / 49.3%
- Top-2 symbol concentration: 47.5%
- Trades closed in plunge: 443
- Win rate: 52.4%
- Avg PnL: $-2.77
- Max loss streak: 9

### Cluster 2
- Start: 2026-01-20
- Trough: 2026-02-03
- Recovery: ONGOING
- Max DD: 6.92%
- Duration: 24 days
- Trades open: 31
- Long/Short: 45.2% / 54.8%
- Top-2 symbol concentration: 67.7%
- Trades closed in plunge: 31
- Win rate: 41.9%
- Avg PnL: $-18.70
- Max loss streak: 6

### Cluster 3
- Start: 2024-10-14
- Trough: 2024-10-31
- Recovery: 2024-11-07
- Max DD: 3.03%
- Duration: 24 days
- Trades open: 41
- Long/Short: 43.9% / 56.1%
- Top-2 symbol concentration: 63.4%
- Trades closed in plunge: 40
- Win rate: 42.5%
- Avg PnL: $-4.97
- Max loss streak: 4

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 9 |
| Avg Streak | 2.2 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $934.13 | 1.05 | 0.00% |
| Slip 1.0 pip RT | $-2,367.77 | 0.89 | 353.47% |
| Spread +50% | $-1,418.51 | 0.93 | 251.85% |
| Severe (1.0 + 75%) | $-5,896.72 | 0.75 | 731.25% |

## Section 10 — Directional Robustness

- Total Longs: 594
- Total Shorts: 567
- Baseline PF: 1.05
- No Top-20 Longs PF: 0.92
- No Top-20 Shorts PF: 0.92
- No Both PF: 0.80

## Section 11 — Early/Late Split

**First Half** (580 trades)
- CAGR: 1.51%
- Max DD: 13.35%
- Win Rate: 52.93%

**Second Half** (581 trades)
- CAGR: 10.82%
- Max DD: 7.02%
- Win Rate: 53.36%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 1143 | 6.83% | 13.38% |
| AUDUSD | 841 | -6.14% | 19.60% |
| EURUSD | 902 | 3.83% | 13.03% |
| GBPNZD | 1057 | 9.10% | 10.32% |
| GBPUSD | 922 | 11.01% | 10.75% |
| USDCHF | 940 | 9.20% | 9.98% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDUSD | 320 | $1,753.28 | 55.0% | +187.7% |
| EURUSD | 259 | $411.97 | 53.3% | +44.1% |
| AUDNZD | 18 | $-0.59 | 66.7% | -0.1% |
| GBPNZD | 104 | $-316.45 | 52.9% | -33.9% |
| USDCHF | 221 | $-330.29 | 54.3% | -35.4% |
| GBPUSD | 239 | $-583.79 | 48.5% | -62.5% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 4.59%
- Median CAGR: 3.35%
- 5th pctl CAGR: -0.23%
- 95th pctl CAGR: 13.06%
- Mean DD: 10.68%
- Worst DD: 13.93%
- Runs ending below start: 90

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 8.01
- Kruskal-Wallis p-value: 0.7122
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 146 | $-344.33 | 0.87 | — |
| 2 | 111 | $-407.34 | 0.81 | — |
| 3 | 84 | $-351.38 | 0.76 | — |
| 4 | 119 | $193.55 | 1.11 | — |
| 5 | 74 | $-306.31 | 0.80 | — |
| 6 | 73 | $673.92 | 1.90 | — |
| 7 | 75 | $35.89 | 1.03 | — |
| 8 | 46 | $108.59 | 1.14 | — |
| 9 | 47 | $10.27 | 1.01 | — |
| 10 | 137 | $53.46 | 1.02 | — |
| 11 | 136 | $311.16 | 1.13 | — |
| 12 | 113 | $956.65 | 1.44 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 3.94 from global mean 0.80
