# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P07 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:23

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 197 |
| Win Rate | 60.4% |
| Avg Win | $328.10 |
| Avg Loss | $251.08 |
| Payoff Ratio | 1.31 |
| Expectancy / Trade | $98.78 |
| Profit Factor | 1.99 |
| Net Profit | $19,459.72 |
| Max DD (USD) | $2,377.64 |
| Recovery Factor | 8.18 |

## Section 2 — Tail Contribution

- Top 1 trade: 6.46%
- Top 5 trades: 27.47%
- Top 1% (1): 6.46%
- Top 5% (9): 43.57%
- Total PnL: $19,459.72

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 90.97%
- New CAGR: 86.05%
- Degradation: 5.41%
- New Equity: $28,201.82

**Removing Top 5% (9 trades)**
- Original CAGR: 90.97%
- New CAGR: 55.86%
- Degradation: 38.60%
- New Equity: $20,981.87

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 27
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 8, NORMAL: 13
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.81%
- Median CAGR: 0.79%
- 5th pctl CAGR: 0.35%
- 95th pctl CAGR: 1.32%
- Mean DD: 11.17%
- 95th pctl DD: 14.53%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 14.53%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.34% |
| 15.00% | 0.52% |
| 20.00% | 0.69% |
| 25.00% | 0.86% |
| 30.00% | 1.03% |

**Kelly Fraction**

- Full Kelly: 0.3011
- Safe fraction (½ Kelly): 0.1505

## Section 5 — Reverse Path Test

- Final Equity: $29,459.72
- CAGR: 91.17%
- Max DD: 12.90%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 9
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 43.65%
- Worst DD: 12.90%
- Mean return: 65.24%
- Mean DD: 12.90%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 99 | $6,013.21 | 57.6% | $60.74 |
| 2025 | 98 | $13,446.51 | 63.3% | $137.21 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | Jun | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +173 | +225 | +2281 | +0 | +67 | +1748 | -399 | +1487 | +2041 | -1611 |
| 2025 | +2905 | +519 | +1276 | -91 | -744 | -288 | +3491 | +6377 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-01-22
- Max DD: 12.90%
- Duration: 83 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-195.33
- Max loss streak: 3

### Cluster 2
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-27
- Max DD: 10.88%
- Duration: 35 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-296.93
- Max loss streak: 4

### Cluster 3
- Start: 2024-07-17
- Trough: 2024-09-03
- Recovery: 2024-09-24
- Max DD: 9.70%
- Duration: 69 days
- Trades open: 11
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 11
- Win rate: 27.3%
- Avg PnL: $-119.18
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 6 |
| Avg Streak | 2.4 | 1.6 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $19,459.72 | 1.99 | 0.00% |
| Slip 1.0 pip RT | $19,155.62 | 1.97 | 1.56% |
| Spread +50% | $19,231.65 | 1.98 | 1.17% |
| Severe (1.0 + 75%) | $18,813.51 | 1.95 | 3.32% |

## Section 10 — Directional Robustness

- Total Longs: 197
- Total Shorts: 0
- Baseline PF: 1.99
- No Top-20 Longs PF: 1.18
- No Top-20 Shorts PF: 1.99
- No Both PF: 1.18

## Section 11 — Early/Late Split

**First Half** (98 trades)
- CAGR: 108.57%
- Max DD: 9.70%
- Win Rate: 58.16%

**Second Half** (99 trades)
- CAGR: 139.49%
- Max DD: 16.69%
- Win Rate: 62.63%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 197 | $19,459.72 | 60.4% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 94.77%
- Median CAGR: 93.27%
- 5th pctl CAGR: 56.69%
- 95th pctl CAGR: 138.81%
- Mean DD: 15.63%
- Worst DD: 19.59%
- Runs ending below start: 53

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 197 trades < 300 threshold
- Dispersion: max deviation 501.52 from global mean 98.78

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 147.35 from global mean 98.78
