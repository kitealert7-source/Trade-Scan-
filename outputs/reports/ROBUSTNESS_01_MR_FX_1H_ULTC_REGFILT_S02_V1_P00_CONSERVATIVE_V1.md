# ROBUSTNESS REPORT — 01_MR_FX_1H_ULTC_REGFILT_S02_V1_P00 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 16:35:57

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2178 |
| Win Rate | 59.0% |
| Avg Win | $10.42 |
| Avg Loss | $12.81 |
| Payoff Ratio | 0.81 |
| Expectancy / Trade | $0.91 |
| Profit Factor | 1.18 |
| Net Profit | $2,064.28 |
| Max DD (USD) | $464.29 |
| Recovery Factor | 4.45 |

## Section 2 — Tail Contribution

- Top 1 trade: 5.65%
- Top 5 trades: 23.22%
- Top 1% (21): 57.81%
- Top 5% (108): 169.92%
- Total PnL: $2,064.28

## Section 3 — Tail Removal

**Removing Top 1% (21 trades)**
- Original CAGR: 14.45%
- New CAGR: 6.19%
- Degradation: 57.16%
- New Equity: $10,870.96

**Removing Top 5% (108 trades)**
- Original CAGR: 14.45%
- New CAGR: -10.61%
- Degradation: 173.38%
- New Equity: $8,556.73

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 205
- Regime Distribution: HIGH_VOL: 52, LOW_VOL: 51, NORMAL: 102
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.14%
- Median CAGR: 0.14%
- 5th pctl CAGR: 0.04%
- 95th pctl CAGR: 0.24%
- Mean DD: 4.77%
- 95th pctl DD: 7.91%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 7.91%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.63% |
| 15.00% | 0.95% |
| 20.00% | 1.26% |
| 25.00% | 1.58% |
| 30.00% | 1.90% |

**Kelly Fraction**

- Full Kelly: 0.0870
- Safe fraction (½ Kelly): 0.0435

## Section 5 — Reverse Path Test

- Final Equity: $12,069.65
- CAGR: 14.48%
- Max DD: 4.28%
- Max Loss Streak: 13

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 8.20%
- Worst DD: 3.94%
- Mean return: 11.62%
- Mean DD: 3.58%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 390 | $636.48 | 56.7% | $1.63 |
| 2025 | 1570 | $1,224.67 | 59.4% | $0.78 |
| 2026 | 218 | $203.13 | 60.6% | $0.93 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +91 | +257 | +288 |
| 2025 | +245 | -1 | -16 | +159 | +75 | +217 | +160 | +60 | +85 | -212 | +188 | +266 |
| 2026 | -105 | +309 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-08-20
- Trough: 2025-11-04
- Recovery: 2025-12-15
- Max DD: 3.94%
- Duration: 117 days
- Trades open: 340
- Long/Short: 56.5% / 43.5%
- Top-2 symbol concentration: 43.2%
- Trades closed in plunge: 337
- Win rate: 58.2%
- Avg PnL: $-1.14
- Max loss streak: 8

### Cluster 2
- Start: 2025-12-30
- Trough: 2026-01-28
- Recovery: 2026-02-18
- Max DD: 2.13%
- Duration: 50 days
- Trades open: 103
- Long/Short: 52.4% / 47.6%
- Top-2 symbol concentration: 48.5%
- Trades closed in plunge: 102
- Win rate: 55.9%
- Avg PnL: $-1.98
- Max loss streak: 13

### Cluster 3
- Start: 2025-03-17
- Trough: 2025-03-26
- Recovery: 2025-04-22
- Max DD: 1.39%
- Duration: 36 days
- Trades open: 45
- Long/Short: 60.0% / 40.0%
- Top-2 symbol concentration: 53.3%
- Trades closed in plunge: 45
- Win rate: 46.7%
- Avg PnL: $-2.29
- Max loss streak: 5

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 16 | 13 |
| Avg Streak | 2.6 | 1.8 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $2,064.28 | 1.18 | 0.00% |
| Slip 1.0 pip RT | $-709.22 | 0.94 | 134.36% |
| Spread +50% | $-644.26 | 0.95 | 131.21% |
| Severe (1.0 + 75%) | $-4,772.04 | 0.67 | 331.17% |

## Section 10 — Directional Robustness

- Total Longs: 1174
- Total Shorts: 1004
- Baseline PF: 1.18
- No Top-20 Longs PF: 1.09
- No Top-20 Shorts PF: 1.12
- No Both PF: 1.02

## Section 11 — Early/Late Split

**First Half** (1089 trades)
- CAGR: 17.35%
- Max DD: 1.73%
- Win Rate: 58.22%

**Second Half** (1089 trades)
- CAGR: 13.36%
- Max DD: 4.71%
- Win Rate: 59.87%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 1753 | 9.19% | 5.32% |
| AUDUSD | 1711 | 10.99% | 3.93% |
| EURUSD | 1740 | 12.90% | 2.58% |
| GBPNZD | 1804 | 12.35% | 4.77% |
| GBPUSD | 1704 | 12.66% | 2.56% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDNZD | 425 | $763.80 | 63.8% | +37.0% |
| AUDUSD | 467 | $503.94 | 57.0% | +24.4% |
| GBPNZD | 374 | $309.18 | 62.0% | +15.0% |
| GBPUSD | 474 | $261.50 | 57.8% | +12.7% |
| EURUSD | 438 | $225.86 | 55.5% | +10.9% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 8.25%
- Median CAGR: 7.48%
- 5th pctl CAGR: 4.47%
- 95th pctl CAGR: 13.57%
- Mean DD: 8.48%
- Worst DD: 10.87%
- Runs ending below start: 23

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 4.74
- Kruskal-Wallis p-value: 0.9432
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 260 | $139.72 | 1.10 | — |
| 2 | 247 | $307.67 | 1.27 | — |
| 3 | 145 | $-16.10 | 0.98 | — |
| 4 | 158 | $158.56 | 1.21 | — |
| 5 | 117 | $74.88 | 1.13 | — |
| 6 | 115 | $216.56 | 1.46 | — |
| 7 | 159 | $159.72 | 1.18 | — |
| 8 | 105 | $60.03 | 1.08 | — |
| 9 | 126 | $84.92 | 1.13 | — |
| 10 | 277 | $-120.96 | 0.93 | — |
| 11 | 272 | $445.00 | 1.34 | — |
| 12 | 197 | $554.28 | 1.55 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 0.76 from global mean 0.95
