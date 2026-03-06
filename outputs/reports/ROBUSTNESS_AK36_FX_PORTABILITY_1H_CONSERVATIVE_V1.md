# ROBUSTNESS REPORT — AK36_FX_PORTABILITY_1H / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-03-05 16:49:02

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 90 |
| Win Rate | 47.8% |
| Avg Win | $336.52 |
| Avg Loss | $205.58 |
| Payoff Ratio | 1.64 |
| Expectancy / Trade | $53.42 |
| Profit Factor | 1.50 |
| Net Profit | $4,807.80 |
| Max DD (USD) | $2,300.13 |
| Recovery Factor | 2.09 |

## Section 2 — Tail Contribution

- Top 1 trade: 26.90%
- Top 5 trades: 107.10%
- Top 1% (1): 26.90%
- Top 5% (4): 92.19%
- Total PnL: $4,807.80

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 20.24%
- New CAGR: 15.19%
- Degradation: 24.95%
- New Equity: $13,514.65

**Removing Top 5% (4 trades)**
- Original CAGR: 20.24%
- New CAGR: 1.74%
- Degradation: 91.38%
- New Equity: $10,375.33

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.22%
- Median CAGR: 0.22%
- 5th pctl CAGR: 0.21%
- 95th pctl CAGR: 0.22%
- Mean DD: 16.86%
- 95th pctl DD: 25.36%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $15,145.27
- CAGR: 21.52%
- Max DD: 17.95%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 1
- Return < -10%: 0
- DD > 15%: 7
- DD > 20%: 0
- Worst return: -1.71%
- Worst DD: 18.19%
- Mean return: 11.00%
- Mean DD: 15.79%
- Negative clustering: ISOLATED (Only 1)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 43 | $2,019.93 | 44.2% | $46.98 |
| 2025 | 42 | $1,652.12 | 52.4% | $39.34 |
| 2026 | 5 | $1,135.75 | 40.0% | $227.15 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +621 | +294 | +612 | -1037 | -333 | +871 | -881 | +2086 | -212 |
| 2025 | -631 | -472 | +1034 | -508 | -114 | +0 | -513 | +663 | +85 | +1471 | +636 |
| 2026 | +1284 | -149 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-11-08
- Trough: 2025-04-10
- Recovery: 2025-11-26
- Max DD: 18.19%
- Duration: 383 days
- Trades open: 29
- Long/Short: 48.3% / 51.7%
- Top-2 symbol concentration: 72.4%
- Trades closed in plunge: 26
- Win rate: 34.6%
- Avg PnL: $-77.93
- Max loss streak: 5

### Cluster 2
- Start: 2024-06-04
- Trough: 2024-08-05
- Recovery: 2024-11-06
- Max DD: 12.27%
- Duration: 155 days
- Trades open: 8
- Long/Short: 50.0% / 50.0%
- Top-2 symbol concentration: 87.5%
- Trades closed in plunge: 7
- Win rate: 28.6%
- Avg PnL: $-186.13
- Max loss streak: 3

### Cluster 3
- Start: 2024-03-15
- Trough: 2024-04-04
- Recovery: 2024-05-30
- Max DD: 3.74%
- Duration: 76 days
- Trades open: 4
- Long/Short: 50.0% / 50.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 3
- Win rate: 0.0%
- Avg PnL: $-122.37
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 5 | 6 |
| Avg Streak | 2.1 | 2.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $4,807.80 | 1.50 | 0.00% |
| Slip 1.0 pip RT | $4,516.00 | 1.46 | 6.07% |
| Spread +50% | $4,610.79 | 1.47 | 4.10% |
| Severe (1.0 + 75%) | $4,220.48 | 1.42 | 12.22% |

## Section 10 — Directional Robustness

- Total Longs: 47
- Total Shorts: 43
- Baseline PF: 1.50
- No Top-20 Longs PF: 0.71
- No Top-20 Shorts PF: 0.80
- No Both PF: 0.02

## Section 11 — Early/Late Split

**First Half** (45 trades)
- CAGR: 15.36%
- Max DD: 12.27%
- Win Rate: 42.22%

**Second Half** (45 trades)
- CAGR: 29.19%
- Max DD: 15.55%
- Win Rate: 53.33%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 50 | 19.66% | 10.46% |
| GBPUSD | 61 | 7.75% | 18.88% |
| NZDUSD | 69 | 14.06% | 11.95% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| GBPUSD | 29 | $3,083.72 | 55.2% | +64.1% |
| NZDUSD | 21 | $1,572.53 | 52.4% | +32.7% |
| AUDUSD | 40 | $151.55 | 40.0% | +3.2% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 13.24%
- Median CAGR: 12.72%
- 5th pctl CAGR: 4.43%
- 95th pctl CAGR: 24.46%
- Mean DD: 12.87%
- Worst DD: 16.59%
- Runs ending below start: 48

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 90 trades < 300 threshold
- Dispersion: max deviation 399.13 from global mean 53.42

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: 90 trades < 200 threshold
- Dispersion: max deviation 203.33 from global mean 53.42
