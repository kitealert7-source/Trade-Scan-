# ROBUSTNESS REPORT — 01_MR_FX_1D_RSIAVG_TRENDFILT_S01_V1_P03 / MIN_LOT_FALLBACK_UNCAPPED_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-10 17:32:41

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 204 |
| Win Rate | 65.7% |
| Avg Win | $30.23 |
| Avg Loss | $40.02 |
| Payoff Ratio | 0.76 |
| Expectancy / Trade | $6.12 |
| Profit Factor | 1.45 |
| Net Profit | $1,249.11 |
| Max DD (USD) | $731.55 |
| Recovery Factor | 1.71 |

## Section 2 — Tail Contribution

- Top 1 trade: 15.07%
- Top 5 trades: 49.54%
- Top 1% (2): 24.39%
- Top 5% (10): 83.23%
- Total PnL: $1,249.11

## Section 3 — Tail Removal

**Removing Top 1% (2 trades)**
- Original CAGR: 5.74%
- New CAGR: 4.37%
- Degradation: 23.83%
- New Equity: $10,944.43

**Removing Top 5% (10 trades)**
- Original CAGR: 5.74%
- New CAGR: 0.99%
- Degradation: 82.79%
- New Equity: $10,209.42

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 22
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 8, NORMAL: 10
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.05%
- Median CAGR: 0.05%
- 5th pctl CAGR: -0.00%
- 95th pctl CAGR: 0.10%
- Mean DD: 5.24%
- 95th pctl DD: 8.59%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 8.59%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.58% |
| 15.00% | 0.87% |
| 20.00% | 1.16% |
| 25.00% | 1.45% |
| 30.00% | 1.75% |

**Kelly Fraction**

- Full Kelly: 0.2026
- Safe fraction (½ Kelly): 0.1013

## Section 5 — Reverse Path Test

- Final Equity: $11,244.37
- CAGR: 5.73%
- Max DD: 6.81%
- Max Loss Streak: 7

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 1
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -0.41%
- Worst DD: 6.81%
- Mean return: 2.96%
- Mean DD: 6.13%
- Negative clustering: ISOLATED (Only 1)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 107 | $547.75 | 68.2% | $5.12 |
| 2025 | 83 | $262.17 | 59.0% | $3.16 |
| 2026 | 14 | $439.19 | 85.7% | $31.37 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -2 | +123 | +173 | -293 | +95 | +151 | +119 | +148 | +7 | +40 | +155 | -168 |
| 2025 | +128 | -191 | -46 | +52 | +0 | +183 | +151 | -43 | -38 | +132 | -204 | +139 |
| 2026 | +316 | +123 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-02-27
- Trough: 2025-04-08
- Recovery: 2025-07-23
- Max DD: 6.81%
- Duration: 146 days
- Trades open: 23
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 30.4%
- Trades closed in plunge: 18
- Win rate: 22.2%
- Avg PnL: $-40.64
- Max loss streak: 7

### Cluster 2
- Start: 2024-04-10
- Trough: 2024-04-19
- Recovery: 2024-07-12
- Max DD: 3.65%
- Duration: 93 days
- Trades open: 7
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 28.6%
- Trades closed in plunge: 7
- Win rate: 14.3%
- Avg PnL: $-53.92
- Max loss streak: 3

### Cluster 3
- Start: 2024-07-24
- Trough: 2024-07-25
- Recovery: 2024-08-08
- Max DD: 2.38%
- Duration: 15 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 40.0%
- Trades closed in plunge: 4
- Win rate: 0.0%
- Avg PnL: $-62.09
- Max loss streak: 4

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 13 | 7 |
| Avg Streak | 5.2 | 2.7 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $1,249.11 | 1.45 | 0.00% |
| Slip 1.0 pip RT | $1,212.91 | 1.43 | 2.90% |
| Spread +50% | $1,221.96 | 1.43 | 2.17% |
| Severe (1.0 + 75%) | $1,172.18 | 1.41 | 6.16% |

## Section 10 — Directional Robustness

- Total Longs: 204
- Total Shorts: 0
- Baseline PF: 1.45
- No Top-20 Longs PF: 0.86
- No Top-20 Shorts PF: 1.45
- No Both PF: 0.86

## Section 11 — Early/Late Split

**First Half** (102 trades)
- CAGR: 5.82%
- Max DD: 3.65%
- Win Rate: 69.61%

**Second Half** (102 trades)
- CAGR: 5.97%
- Max DD: 7.17%
- Win Rate: 61.76%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUS200 | 181 | 5.63% | 6.33% |
| ESP35 | 185 | 4.99% | 7.08% |
| EUSTX50 | 183 | 4.90% | 6.61% |
| FRA40 | 181 | 5.76% | 6.14% |
| GER40 | 179 | 4.87% | 6.31% |
| JPN225 | 183 | 5.97% | 3.52% |
| NAS100 | 185 | 4.74% | 6.51% |
| SPX500 | 187 | 5.05% | 6.55% |
| UK100 | 186 | 5.86% | 6.67% |
| US30 | 186 | 4.13% | 7.30% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| US30 | 18 | $360.77 | 66.7% | +28.9% |
| NAS100 | 19 | $226.05 | 73.7% | +18.1% |
| GER40 | 25 | $195.58 | 64.0% | +15.7% |
| EUSTX50 | 21 | $190.24 | 71.4% | +15.2% |
| ESP35 | 19 | $169.24 | 63.2% | +13.5% |
| SPX500 | 17 | $155.55 | 82.4% | +12.5% |
| AUS200 | 23 | $26.21 | 60.9% | +2.1% |
| FRA40 | 23 | $-1.45 | 60.9% | -0.1% |
| UK100 | 18 | $-23.85 | 61.1% | -1.9% |
| JPN225 | 21 | $-49.23 | 57.1% | -3.9% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 3.73%
- Median CAGR: 3.03%
- 5th pctl CAGR: 0.90%
- 95th pctl CAGR: 7.77%
- Mean DD: 4.07%
- Worst DD: 5.82%
- Runs ending below start: 85

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 204 trades < 300 threshold
- Dispersion: max deviation 17.15 from global mean 6.12

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 17.74 from global mean 6.12
