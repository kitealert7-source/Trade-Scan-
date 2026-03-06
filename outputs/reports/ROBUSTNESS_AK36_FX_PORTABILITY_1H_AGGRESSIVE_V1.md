# ROBUSTNESS REPORT — AK36_FX_PORTABILITY_1H / AGGRESSIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-03-05 16:49:02

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 41 |
| Win Rate | 48.8% |
| Avg Win | $649.13 |
| Avg Loss | $465.40 |
| Payoff Ratio | 1.39 |
| Expectancy / Trade | $78.27 |
| Profit Factor | 1.33 |
| Net Profit | $3,209.14 |
| Max DD (USD) | $5,833.53 |
| Recovery Factor | 0.55 |

## Section 2 — Tail Contribution

- Top 1 trade: 81.68%
- Top 5 trades: 239.43%
- Top 1% (1): 81.68%
- Top 5% (2): 126.24%
- Total PnL: $3,209.14

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 13.96%
- New CAGR: 2.72%
- Degradation: 80.52%
- New Equity: $10,587.98

**Removing Top 5% (2 trades)**
- Original CAGR: 13.96%
- New CAGR: -4.05%
- Degradation: 128.98%
- New Equity: $9,158.06

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.14%
- Median CAGR: 0.14%
- 5th pctl CAGR: 0.13%
- 95th pctl CAGR: 0.15%
- Mean DD: 28.31%
- 95th pctl DD: 39.15%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $13,407.47
- CAGR: 14.76%
- Max DD: 38.52%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 10
- Return < -10%: 5
- DD > 15%: 14
- DD > 20%: 13
- Worst return: -18.78%
- Worst DD: 38.61%
- Mean return: -2.40%
- Mean DD: 33.47%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 18 | $1,903.92 | 50.0% | $105.77 |
| 2025 | 21 | $1,346.74 | 47.6% | $64.13 |
| 2026 | 2 | $-41.52 | 50.0% | $-20.76 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jul | Aug | Sep | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +929 | -19 | +213 | +386 | +1424 | -518 | +2621 | -3133 |
| 2025 | -681 | -1576 | +657 | +124 | -167 | +0 | +830 | -308 | +1430 | +1038 |
| 2026 | +0 | -42 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-11-08
- Trough: 2025-04-10
- Recovery: ONGOING
- Max DD: 38.61%
- Duration: 468 days
- Trades open: 17
- Long/Short: 47.1% / 52.9%
- Top-2 symbol concentration: 94.1%
- Trades closed in plunge: 14
- Win rate: 35.7%
- Avg PnL: $-379.16
- Max loss streak: 4

### Cluster 2
- Start: 2024-03-22
- Trough: 2024-05-02
- Recovery: 2024-07-19
- Max DD: 6.80%
- Duration: 119 days
- Trades open: 3
- Long/Short: 33.3% / 66.7%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 0.0%
- Avg PnL: $-215.65
- Max loss streak: 2

### Cluster 3
- Start: 2024-09-26
- Trough: 2024-09-26
- Recovery: 2024-11-06
- Max DD: 4.00%
- Duration: 41 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-517.65
- Max loss streak: 1

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 3 | 4 |
| Avg Streak | 2.0 | 2.1 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $3,209.14 | 1.33 | 0.00% |
| Slip 1.0 pip RT | $2,942.94 | 1.30 | 8.30% |
| Spread +50% | $3,036.91 | 1.31 | 5.37% |
| Severe (1.0 + 75%) | $2,684.60 | 1.27 | 16.35% |

## Section 10 — Directional Robustness

- Total Longs: 24
- Total Shorts: 17
- Baseline PF: 1.33
- No Top-20 Longs PF: 0.86
- No Top-20 Shorts PF: 1.33
- No Both PF: 0.86

## Section 11 — Early/Late Split

**First Half** (20 trades)
- CAGR: 9.79%
- Max DD: 26.99%
- Win Rate: 45.00%

**Second Half** (21 trades)
- CAGR: 20.10%
- Max DD: 19.12%
- Win Rate: 52.38%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 15 | 8.51% | 10.96% |
| GBPUSD | 36 | 7.31% | 38.84% |
| NZDUSD | 31 | 13.63% | 35.82% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| GBPUSD | 5 | $1,586.76 | 80.0% | +49.4% |
| AUDUSD | 26 | $1,540.80 | 42.3% | +48.0% |
| NZDUSD | 10 | $81.58 | 50.0% | +2.5% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 6.35%
- Median CAGR: 5.86%
- 5th pctl CAGR: 2.83%
- 95th pctl CAGR: 8.76%
- Mean DD: 13.70%
- Worst DD: 20.76%
- Runs ending below start: 86

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 41 trades < 300 threshold
- Dispersion: max deviation 776.60 from global mean 78.27

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: 41 trades < 200 threshold
- Dispersion: max deviation 500.66 from global mean 78.27
