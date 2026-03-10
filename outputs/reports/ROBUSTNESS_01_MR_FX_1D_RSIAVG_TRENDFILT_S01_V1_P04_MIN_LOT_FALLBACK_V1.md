# ROBUSTNESS REPORT — 01_MR_FX_1D_RSIAVG_TRENDFILT_S01_V1_P04 / MIN_LOT_FALLBACK_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-10 17:49:38

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 417 |
| Win Rate | 63.3% |
| Avg Win | $26.12 |
| Avg Loss | $37.09 |
| Payoff Ratio | 0.70 |
| Expectancy / Trade | $2.93 |
| Profit Factor | 1.21 |
| Net Profit | $1,219.89 |
| Max DD (USD) | $873.67 |
| Recovery Factor | 1.40 |

## Section 2 — Tail Contribution

- Top 1 trade: 9.54%
- Top 5 trades: 41.14%
- Top 1% (4): 34.12%
- Top 5% (20): 130.64%
- Total PnL: $1,219.89

## Section 3 — Tail Removal

**Removing Top 1% (4 trades)**
- Original CAGR: 3.02%
- New CAGR: 2.02%
- Degradation: 33.17%
- New Equity: $10,803.71

**Removing Top 5% (20 trades)**
- Original CAGR: 3.02%
- New CAGR: -0.98%
- Degradation: 132.44%
- New Equity: $9,626.26

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 36
- Regime Distribution: HIGH_VOL: 7, LOW_VOL: 11, NORMAL: 18
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.03%
- Median CAGR: 0.03%
- 5th pctl CAGR: -0.02%
- 95th pctl CAGR: 0.08%
- Mean DD: 10.09%
- 95th pctl DD: 18.36%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 18.36%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.27% |
| 15.00% | 0.41% |
| 20.00% | 0.54% |
| 25.00% | 0.68% |
| 30.00% | 0.82% |

**Kelly Fraction**

- Full Kelly: 0.1120
- Safe fraction (½ Kelly): 0.0560

## Section 5 — Reverse Path Test

- Final Equity: $11,229.82
- CAGR: 3.04%
- Max DD: 8.87%
- Max Loss Streak: 11

## Section 6 — Rolling 1-Year Window

- Total windows: 35
- Negative windows: 4
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -6.43%
- Worst DD: 8.67%
- Mean return: 4.11%
- Mean DD: 5.22%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2022 | 94 | $-407.08 | 55.3% | $-4.33 |
| 2023 | 119 | $567.52 | 64.7% | $4.77 |
| 2024 | 109 | $639.43 | 69.7% | $5.87 |
| 2025 | 82 | $169.13 | 58.5% | $2.06 |
| 2026 | 13 | $250.89 | 84.6% | $19.30 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2022 | +0 | +0 | +0 | +40 | +79 | -444 | +339 | -175 | -589 | +107 | +162 | +73 |
| 2023 | +46 | -58 | -224 | +106 | +151 | +124 | +285 | +116 | +31 | -186 | +132 | +44 |
| 2024 | -38 | +123 | +173 | -293 | +95 | +151 | +119 | +148 | +46 | +60 | +223 | -168 |
| 2025 | +128 | -191 | -46 | -56 | +0 | +183 | +151 | -43 | -38 | +132 | -204 | +154 |
| 2026 | +128 | +123 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2022-06-10
- Trough: 2022-10-03
- Recovery: 2023-08-14
- Max DD: 8.67%
- Duration: 430 days
- Trades open: 48
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 29.2%
- Trades closed in plunge: 47
- Win rate: 31.9%
- Avg PnL: $-19.14
- Max loss streak: 11

### Cluster 2
- Start: 2025-02-27
- Trough: 2025-04-08
- Recovery: 2025-10-20
- Max DD: 6.65%
- Duration: 235 days
- Trades open: 23
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 30.4%
- Trades closed in plunge: 18
- Win rate: 22.2%
- Avg PnL: $-40.64
- Max loss streak: 7

### Cluster 3
- Start: 2024-04-10
- Trough: 2024-04-19
- Recovery: 2024-07-12
- Max DD: 3.60%
- Duration: 93 days
- Trades open: 7
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 28.6%
- Trades closed in plunge: 7
- Win rate: 14.3%
- Avg PnL: $-53.86
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 13 | 11 |
| Avg Streak | 4.6 | 2.7 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $1,219.89 | 1.21 | 0.00% |
| Slip 1.0 pip RT | $1,141.19 | 1.20 | 6.45% |
| Spread +50% | $1,160.87 | 1.20 | 4.84% |
| Severe (1.0 + 75%) | $1,052.65 | 1.18 | 13.71% |

## Section 10 — Directional Robustness

- Total Longs: 417
- Total Shorts: 0
- Baseline PF: 1.21
- No Top-20 Longs PF: 0.93
- No Top-20 Shorts PF: 1.21
- No Both PF: 0.93

## Section 11 — Early/Late Split

**First Half** (208 trades)
- CAGR: 0.71%
- Max DD: 8.89%
- Win Rate: 60.10%

**Second Half** (209 trades)
- CAGR: 4.81%
- Max DD: 6.72%
- Win Rate: 66.51%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUS200 | 370 | 3.16% | 8.13% |
| ESP35 | 373 | 2.48% | 7.98% |
| EUSTX50 | 376 | 2.22% | 7.80% |
| FRA40 | 375 | 3.04% | 7.90% |
| GER40 | 372 | 2.50% | 8.60% |
| JPN225 | 380 | 3.51% | 8.20% |
| NAS100 | 372 | 1.86% | 9.08% |
| SPX500 | 377 | 2.90% | 8.20% |
| UK100 | 380 | 3.43% | 7.82% |
| US30 | 378 | 2.16% | 7.56% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| NAS100 | 45 | $480.74 | 73.3% | +39.4% |
| US30 | 39 | $357.63 | 66.7% | +29.3% |
| EUSTX50 | 41 | $333.71 | 68.3% | +27.4% |
| ESP35 | 44 | $225.01 | 65.9% | +18.4% |
| GER40 | 45 | $216.19 | 60.0% | +17.7% |
| SPX500 | 40 | $49.71 | 67.5% | +4.1% |
| FRA40 | 42 | $-7.02 | 61.9% | -0.6% |
| AUS200 | 47 | $-58.17 | 57.4% | -4.8% |
| UK100 | 37 | $-173.81 | 54.1% | -14.2% |
| JPN225 | 37 | $-204.10 | 56.8% | -16.7% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 2.04%
- Median CAGR: 1.79%
- 5th pctl CAGR: 0.35%
- 95th pctl CAGR: 5.11%
- Mean DD: 7.58%
- Worst DD: 12.59%
- Runs ending below start: 27

## Section 15 — Monthly Seasonality [MEDIUM MODE]

**Verdict:** Significant calendar pattern
- Kruskal-Wallis H: 34.50
- Kruskal-Wallis p-value: 0.0003
- Effect size (η²): 0.0580

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 23 | $264.01 | 2.21 | — |
| 2 | 28 | $-3.09 | 0.99 | — |
| 3 | 20 | $-97.58 | 0.76 | — |
| 4 | 37 | $-203.06 | 0.77 | — |
| 5 | 31 | $325.05 | 2.78 | — |
| 6 | 48 | $13.66 | 1.02 | — |
| 7 | 38 | $894.28 | 4.60 | — |
| 8 | 39 | $45.86 | 1.09 | — |
| 9 | 46 | $-550.07 | 0.40 | — |
| 10 | 39 | $113.38 | 1.26 | — |
| 11 | 32 | $313.63 | 2.19 | — |
| 12 | 36 | $103.82 | 1.26 | — |

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 10.06 from global mean 2.93
