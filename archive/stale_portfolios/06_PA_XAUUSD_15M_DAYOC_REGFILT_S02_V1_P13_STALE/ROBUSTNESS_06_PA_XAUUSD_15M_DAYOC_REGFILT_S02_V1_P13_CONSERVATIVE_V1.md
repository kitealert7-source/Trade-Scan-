# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P13 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:49:12

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 116 |
| Win Rate | 63.8% |
| Avg Win | $99.88 |
| Avg Loss | $80.02 |
| Payoff Ratio | 1.25 |
| Expectancy / Trade | $34.74 |
| Profit Factor | 2.20 |
| Net Profit | $4,030.04 |
| Max DD (USD) | $767.30 |
| Recovery Factor | 5.25 |

## Section 2 — Tail Contribution

- Top 1 trade: 8.91%
- Top 5 trades: 36.38%
- Top 1% (1): 8.91%
- Top 5% (5): 36.38%
- Total PnL: $4,030.04

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 23.25%
- New CAGR: 21.29%
- Degradation: 8.42%
- New Equity: $13,670.85

**Removing Top 5% (5 trades)**
- Original CAGR: 23.25%
- New CAGR: 15.13%
- Degradation: 34.92%
- New Equity: $12,563.82

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 23
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 7, NORMAL: 10
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.22%
- Median CAGR: 0.21%
- 5th pctl CAGR: 0.08%
- 95th pctl CAGR: 0.37%
- Mean DD: 6.07%
- 95th pctl DD: 9.51%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 9.51%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.53% |
| 15.00% | 0.79% |
| 20.00% | 1.05% |
| 25.00% | 1.32% |
| 30.00% | 1.58% |

**Kelly Fraction**

- Full Kelly: 0.3478
- Safe fraction (½ Kelly): 0.1739

## Section 5 — Reverse Path Test

- Final Equity: $14,030.04
- CAGR: 23.37%
- Max DD: 6.35%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 12.39%
- Worst DD: 6.35%
- Mean return: 15.44%
- Mean DD: 6.35%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 60 | $1,319.92 | 60.0% | $22.00 |
| 2025 | 56 | $2,710.12 | 67.9% | $48.40 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +145 | +510 | +0 | +0 | +509 | +669 | -514 |
| 2025 | +622 | +34 | +0 | -178 | +905 | +1327 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-08-07
- Max DD: 6.35%
- Duration: 280 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-66.25
- Max loss streak: 3

### Cluster 2
- Start: 2025-08-11
- Trough: 2025-08-19
- Recovery: 2025-08-26
- Max DD: 2.40%
- Duration: 15 days
- Trades open: 6
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 6
- Win rate: 50.0%
- Avg PnL: $-28.77
- Max loss streak: 1

### Cluster 3
- Start: 2024-09-27
- Trough: 2024-10-09
- Recovery: 2024-10-15
- Max DD: 2.35%
- Duration: 18 days
- Trades open: 8
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 8
- Win rate: 12.5%
- Avg PnL: $-28.22
- Max loss streak: 5

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 6 |
| Avg Streak | 2.6 | 1.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $4,030.04 | 2.20 | 0.00% |
| Slip 1.0 pip RT | $3,971.74 | 2.17 | 1.45% |
| Spread +50% | $3,986.32 | 2.18 | 1.08% |
| Severe (1.0 + 75%) | $3,906.15 | 2.15 | 3.07% |

## Section 10 — Directional Robustness

- Total Longs: 116
- Total Shorts: 0
- Baseline PF: 2.20
- No Top-20 Longs PF: 0.96
- No Top-20 Shorts PF: 2.20
- No Both PF: 0.96

## Section 11 — Early/Late Split

**First Half** (58 trades)
- CAGR: 25.35%
- Max DD: 2.53%
- Win Rate: 60.34%

**Second Half** (58 trades)
- CAGR: 25.78%
- Max DD: 5.00%
- Win Rate: 67.24%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 116 | $4,030.04 | 63.8% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 58.47%
- Median CAGR: 57.45%
- 5th pctl CAGR: 26.66%
- 95th pctl CAGR: 94.97%
- Mean DD: 13.97%
- Worst DD: 19.54%
- Runs ending below start: 53

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 116 trades < 300 threshold
- Dispersion: max deviation 220.50 from global mean 34.74

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 63.79 from global mean 34.74
