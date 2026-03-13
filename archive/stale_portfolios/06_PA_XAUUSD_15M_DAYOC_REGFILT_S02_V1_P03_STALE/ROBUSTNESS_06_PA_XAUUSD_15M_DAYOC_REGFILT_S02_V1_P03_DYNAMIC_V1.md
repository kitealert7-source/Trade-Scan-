# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P03 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:37:47

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 114 |
| Win Rate | 63.2% |
| Avg Win | $248.43 |
| Avg Loss | $209.19 |
| Payoff Ratio | 1.19 |
| Expectancy / Trade | $79.83 |
| Profit Factor | 2.04 |
| Net Profit | $9,101.12 |
| Max DD (USD) | $1,619.57 |
| Recovery Factor | 5.62 |

## Section 2 — Tail Contribution

- Top 1 trade: 9.21%
- Top 5 trades: 40.43%
- Top 1% (1): 9.21%
- Top 5% (5): 40.43%
- Total PnL: $9,101.12

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 49.48%
- New CAGR: 45.37%
- Degradation: 8.31%
- New Equity: $18,262.52

**Removing Top 5% (5 trades)**
- Original CAGR: 49.48%
- New CAGR: 30.87%
- Degradation: 37.60%
- New Equity: $15,421.78

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 18
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 6, NORMAL: 8
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.45%
- Median CAGR: 0.45%
- 5th pctl CAGR: 0.13%
- 95th pctl CAGR: 0.81%
- Mean DD: 12.49%
- 95th pctl DD: 18.55%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 18.55%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.27% |
| 15.00% | 0.40% |
| 20.00% | 0.54% |
| 25.00% | 0.67% |
| 30.00% | 0.81% |

**Kelly Fraction**

- Full Kelly: 0.3214
- Safe fraction (½ Kelly): 0.1607

## Section 5 — Reverse Path Test

- Final Equity: $19,101.12
- CAGR: 49.48%
- Max DD: 11.69%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 20.09%
- Worst DD: 11.69%
- Mean return: 27.53%
- Mean DD: 11.69%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 54 | $2,237.94 | 61.1% | $41.44 |
| 2025 | 60 | $6,863.18 | 65.0% | $114.39 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +196 | +1051 | +0 | +0 | +669 | +1392 | -1070 |
| 2025 | +1190 | +79 | +0 | -63 | +2101 | +3556 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-07-21
- Max DD: 11.69%
- Duration: 263 days
- Trades open: 2
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 50.0%
- Avg PnL: $-223.75
- Max loss streak: 1

### Cluster 2
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-28
- Max DD: 10.32%
- Duration: 36 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-192.31
- Max loss streak: 4

### Cluster 3
- Start: 2024-09-27
- Trough: 2024-10-08
- Recovery: 2024-10-17
- Max DD: 6.43%
- Duration: 20 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 0.0%
- Avg PnL: $-108.63
- Max loss streak: 5

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 6 |
| Avg Streak | 2.6 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $9,101.12 | 2.04 | 0.00% |
| Slip 1.0 pip RT | $8,963.52 | 2.01 | 1.51% |
| Spread +50% | $8,997.92 | 2.02 | 1.13% |
| Severe (1.0 + 75%) | $8,808.72 | 1.99 | 3.21% |

## Section 10 — Directional Robustness

- Total Longs: 114
- Total Shorts: 0
- Baseline PF: 2.04
- No Top-20 Longs PF: 0.86
- No Top-20 Shorts PF: 2.04
- No Both PF: 0.86

## Section 11 — Early/Late Split

**First Half** (57 trades)
- CAGR: 27.46%
- Max DD: 11.69%
- Win Rate: 61.40%

**Second Half** (57 trades)
- CAGR: 112.25%
- Max DD: 12.44%
- Win Rate: 64.91%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 114 | $9,101.12 | 63.2% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 49.92%
- Median CAGR: 46.69%
- 5th pctl CAGR: 15.95%
- 95th pctl CAGR: 92.63%
- Mean DD: 15.50%
- Worst DD: 18.43%
- Runs ending below start: 53

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 114 trades < 300 threshold
- Dispersion: max deviation 614.80 from global mean 79.83

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 154.44 from global mean 79.83
