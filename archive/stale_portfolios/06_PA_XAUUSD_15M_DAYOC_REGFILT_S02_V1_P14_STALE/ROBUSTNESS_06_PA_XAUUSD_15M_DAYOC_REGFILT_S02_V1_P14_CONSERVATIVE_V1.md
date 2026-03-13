# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P14 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 15:05:09

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 135 |
| Win Rate | 62.2% |
| Avg Win | $102.19 |
| Avg Loss | $79.32 |
| Payoff Ratio | 1.29 |
| Expectancy / Trade | $33.62 |
| Profit Factor | 2.12 |
| Net Profit | $4,538.67 |
| Max DD (USD) | $767.30 |
| Recovery Factor | 5.92 |

## Section 2 — Tail Contribution

- Top 1 trade: 7.91%
- Top 5 trades: 32.74%
- Top 1% (1): 7.91%
- Top 5% (6): 37.93%
- Total PnL: $4,538.67

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 25.81%
- New CAGR: 23.89%
- Degradation: 7.42%
- New Equity: $14,179.48

**Removing Top 5% (6 trades)**
- Original CAGR: 25.81%
- New CAGR: 16.45%
- Degradation: 36.27%
- New Equity: $12,817.10

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 27
- Regime Distribution: HIGH_VOL: 7, LOW_VOL: 8, NORMAL: 12
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.24%
- Median CAGR: 0.24%
- 5th pctl CAGR: 0.09%
- 95th pctl CAGR: 0.40%
- Mean DD: 5.92%
- 95th pctl DD: 8.65%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 8.65%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.58% |
| 15.00% | 0.87% |
| 20.00% | 1.16% |
| 25.00% | 1.45% |
| 30.00% | 1.73% |

**Kelly Fraction**

- Full Kelly: 0.3290
- Safe fraction (½ Kelly): 0.1645

## Section 5 — Reverse Path Test

- Final Equity: $14,538.67
- CAGR: 25.83%
- Max DD: 6.34%
- Max Loss Streak: 6

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 13.39%
- Worst DD: 6.34%
- Mean return: 16.60%
- Mean DD: 6.34%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 63 | $1,326.60 | 58.7% | $21.06 |
| 2025 | 72 | $3,212.07 | 65.3% | $44.61 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +186 | +510 | +0 | +0 | +474 | +669 | -514 |
| 2025 | +652 | +150 | +0 | -149 | +935 | +1625 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-02-04
- Max DD: 6.34%
- Duration: 96 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-66.25
- Max loss streak: 3

### Cluster 2
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-27
- Max DD: 5.11%
- Duration: 35 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-76.24
- Max loss streak: 4

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
| Avg Streak | 2.5 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $4,538.67 | 2.12 | 0.00% |
| Slip 1.0 pip RT | $4,471.17 | 2.10 | 1.49% |
| Spread +50% | $4,488.05 | 2.10 | 1.12% |
| Severe (1.0 + 75%) | $4,395.23 | 2.07 | 3.16% |

## Section 10 — Directional Robustness

- Total Longs: 135
- Total Shorts: 0
- Baseline PF: 2.12
- No Top-20 Longs PF: 1.04
- No Top-20 Shorts PF: 2.12
- No Both PF: 1.04

## Section 11 — Early/Late Split

**First Half** (67 trades)
- CAGR: 15.72%
- Max DD: 6.34%
- Win Rate: 59.70%

**Second Half** (68 trades)
- CAGR: 46.73%
- Max DD: 5.77%
- Win Rate: 64.71%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 135 | $4,538.67 | 62.2% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 63.98%
- Median CAGR: 62.39%
- 5th pctl CAGR: 27.49%
- 95th pctl CAGR: 106.39%
- Mean DD: 15.68%
- Worst DD: 19.38%
- Runs ending below start: 30

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 135 trades < 300 threshold
- Dispersion: max deviation 221.63 from global mean 33.62

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 63.85 from global mean 33.62
