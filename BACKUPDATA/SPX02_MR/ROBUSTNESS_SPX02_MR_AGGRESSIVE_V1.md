# ROBUSTNESS REPORT — SPX02_MR / AGGRESSIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-28 10:25:45

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 164 |
| Win Rate | 65.2% |
| Avg Win | $85.68 |
| Avg Loss | $132.59 |
| Payoff Ratio | 0.65 |
| Expectancy / Trade | $9.82 |
| Profit Factor | 1.21 |
| Net Profit | $1,610.24 |
| Max DD (USD) | $2,399.52 |
| Recovery Factor | 0.67 |

## Section 2 — Tail Contribution

- Top 1 trade: 17.39%
- Top 5 trades: 65.24%
- Top 1% (1): 17.39%
- Top 5% (8): 97.03%
- Total PnL: $1,610.24

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 1.50%
- New CAGR: 1.25%
- Degradation: 16.46%
- New Equity: $11,330.16

**Removing Top 5% (8 trades)**
- Original CAGR: 1.50%
- New CAGR: 0.05%
- Degradation: 96.83%
- New Equity: $10,047.80

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.01%
- Median CAGR: 0.01%
- 5th pctl CAGR: 0.01%
- 95th pctl CAGR: 0.01%
- Mean DD: 13.92%
- 95th pctl DD: 20.24%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $11,610.24
- CAGR: 1.50%
- Max DD: 20.87%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 111
- Negative windows: 48
- Return < -10%: 2
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -13.70%
- Worst DD: 13.70%
- Mean return: 1.06%
- Mean DD: 5.15%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2016 | 12 | $382.11 | 66.7% | $31.84 |
| 2017 | 12 | $1,117.17 | 75.0% | $93.10 |
| 2018 | 21 | $-1,575.80 | 52.4% | $-75.04 |
| 2019 | 14 | $250.40 | 64.3% | $17.89 |
| 2020 | 16 | $-766.79 | 68.8% | $-47.92 |
| 2021 | 14 | $893.74 | 78.6% | $63.84 |
| 2022 | 26 | $-696.25 | 53.8% | $-26.78 |
| 2023 | 16 | $203.75 | 56.2% | $12.73 |
| 2024 | 15 | $980.75 | 80.0% | $65.38 |
| 2025 | 16 | $512.78 | 68.8% | $32.05 |
| 2026 | 2 | $308.38 | 100.0% | $154.19 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | -40 | +17 | +0 | +0 | -2 | +113 | +0 | +0 | +154 | +42 | +96 | +0 |
| 2017 | +176 | +78 | -8 | -30 | +196 | +0 | +184 | +217 | +0 | +0 | +165 | +138 |
| 2018 | +0 | -732 | -172 | -102 | +0 | +146 | +0 | +209 | +36 | -571 | +49 | -439 |
| 2019 | +0 | +0 | +98 | +0 | -245 | +78 | +204 | -113 | +0 | +116 | +0 | +113 |
| 2020 | +9 | -685 | -293 | +0 | +0 | +92 | +97 | +0 | -35 | -107 | +156 | +0 |
| 2021 | +0 | +5 | +56 | +0 | +29 | +203 | +93 | +174 | +44 | -63 | +87 | +266 |
| 2022 | -47 | -96 | +11 | +10 | -70 | -113 | +51 | -113 | -188 | +46 | +23 | -212 |
| 2023 | +130 | -119 | +74 | +123 | +53 | +13 | +0 | -104 | -133 | +55 | +112 | +0 |
| 2024 | +78 | +221 | +0 | +21 | +0 | +59 | -2 | +0 | +50 | +0 | +360 | +195 |
| 2025 | +192 | -173 | -336 | -35 | +74 | +166 | +0 | +266 | +0 | +260 | +2 | +95 |
| 2026 | +308 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2018-02-05
- Trough: 2020-03-19
- Recovery: 2026-01-26
- Max DD: 20.87%
- Duration: 2912 days
- Trades open: 41
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 41
- Win rate: 56.1%
- Avg PnL: $-58.53
- Max loss streak: 3

### Cluster 2
- Start: 2016-01-15
- Trough: 2016-05-04
- Recovery: 2016-05-10
- Max DD: 1.17%
- Duration: 116 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 50.0%
- Avg PnL: $-29.22
- Max loss streak: 1

### Cluster 3
- Start: 2016-05-19
- Trough: 2016-06-17
- Recovery: 2016-06-30
- Max DD: 0.64%
- Duration: 42 days
- Trades open: 2
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 0.0%
- Avg PnL: $-31.82
- Max loss streak: 2

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 4 |
| Avg Streak | 2.8 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $1,610.24 | 1.21 | 0.00% |
| Slip 1.0 pip RT | $1,319.14 | 1.17 | 18.08% |
| Spread +50% | $1,391.91 | 1.18 | 13.56% |
| Severe (1.0 + 75%) | $991.65 | 1.13 | 38.42% |

## Section 10 — Directional Robustness

- Total Longs: 164
- Total Shorts: 0
- Baseline PF: 1.21
- No Top-20 Longs PF: 0.77
- No Top-20 Shorts PF: 1.21
- No Both PF: 0.77

## Section 11 — Early/Late Split

**First Half** (82 trades)
- CAGR: -0.06%
- Max DD: 20.87%
- Win Rate: 65.85%

**Second Half** (82 trades)
- CAGR: 3.53%
- Max DD: 6.84%
- Win Rate: 64.63%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| SPX500 | 164 | $1,610.24 | 65.2% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 0.62%
- Median CAGR: 0.63%
- 5th pctl CAGR: -2.01%
- 95th pctl CAGR: 2.29%
- Mean DD: 10.28%
- Worst DD: 29.16%
- Runs ending below start: 32

## Section 15 — Monthly Seasonality [FULL MODE]

- SUPPRESSED: 164 trades < 300 threshold
- Dispersion: max deviation 115.86 from global mean 9.82

## Section 16 — Weekday Seasonality [FULL MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 35.46 from global mean 9.82
