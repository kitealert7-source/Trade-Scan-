# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P08 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:33

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 172 |
| Win Rate | 60.5% |
| Avg Win | $257.35 |
| Avg Loss | $238.18 |
| Payoff Ratio | 1.08 |
| Expectancy / Trade | $61.44 |
| Profit Factor | 1.65 |
| Net Profit | $10,568.50 |
| Max DD (USD) | $1,941.67 |
| Recovery Factor | 5.44 |

## Section 2 — Tail Contribution

- Top 1 trade: 8.56%
- Top 5 trades: 38.17%
- Top 1% (1): 8.56%
- Top 5% (8): 57.63%
- Total PnL: $10,568.50

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 44.21%
- New CAGR: 40.95%
- Degradation: 7.36%
- New Equity: $19,663.82

**Removing Top 5% (8 trades)**
- Original CAGR: 44.21%
- New CAGR: 20.66%
- Degradation: 53.26%
- New Equity: $14,477.75

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 20
- Regime Distribution: HIGH_VOL: 7, LOW_VOL: 4, NORMAL: 9
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.40%
- Median CAGR: 0.39%
- 5th pctl CAGR: 0.12%
- 95th pctl CAGR: 0.68%
- Mean DD: 13.47%
- 95th pctl DD: 19.98%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 19.98%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.25% |
| 15.00% | 0.38% |
| 20.00% | 0.50% |
| 25.00% | 0.63% |
| 30.00% | 0.75% |

**Kelly Fraction**

- Full Kelly: 0.2388
- Safe fraction (½ Kelly): 0.1194

## Section 5 — Reverse Path Test

- Final Equity: $20,568.50
- CAGR: 44.32%
- Max DD: 12.28%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 12
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 21.26%
- Worst DD: 12.28%
- Mean return: 42.48%
- Mean DD: 12.01%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 82 | $3,868.68 | 59.8% | $47.18 |
| 2025 | 89 | $6,855.58 | 61.8% | $77.03 |
| 2026 | 1 | $-155.76 | 0.0% | $-155.76 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +173 | +225 | +1234 | +36 | +1563 | +0 | +374 | +1571 | -1307 | +0 |
| 2025 | +1800 | +762 | +0 | -767 | -207 | +2666 | +2425 | +0 | +0 | +176 |
| 2026 | -156 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-02-04
- Max DD: 12.28%
- Duration: 96 days
- Trades open: 2
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 50.0%
- Avg PnL: $-259.22
- Max loss streak: 1

### Cluster 2
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-27
- Max DD: 10.64%
- Duration: 35 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-229.50
- Max loss streak: 4

### Cluster 3
- Start: 2024-02-08
- Trough: 2024-02-14
- Recovery: 2024-02-29
- Max DD: 7.22%
- Duration: 21 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 0.0%
- Avg PnL: $-184.15
- Max loss streak: 4

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 6 |
| Avg Streak | 2.4 | 1.6 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $10,568.50 | 1.65 | 0.00% |
| Slip 1.0 pip RT | $10,347.00 | 1.64 | 2.10% |
| Spread +50% | $10,402.38 | 1.64 | 1.57% |
| Severe (1.0 + 75%) | $10,097.81 | 1.62 | 4.45% |

## Section 10 — Directional Robustness

- Total Longs: 172
- Total Shorts: 0
- Baseline PF: 1.65
- No Top-20 Longs PF: 0.89
- No Top-20 Shorts PF: 1.65
- No Both PF: 0.89

## Section 11 — Early/Late Split

**First Half** (86 trades)
- CAGR: 43.68%
- Max DD: 12.28%
- Win Rate: 60.47%

**Second Half** (86 trades)
- CAGR: 63.78%
- Max DD: 14.03%
- Win Rate: 60.47%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 172 | $10,568.50 | 60.5% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 31.68%
- Median CAGR: 29.67%
- 5th pctl CAGR: 8.23%
- 95th pctl CAGR: 52.96%
- Mean DD: 15.63%
- Worst DD: 19.81%
- Runs ending below start: 70

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 172 trades < 300 threshold
- Dispersion: max deviation 715.18 from global mean 61.44

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 103.62 from global mean 61.44
