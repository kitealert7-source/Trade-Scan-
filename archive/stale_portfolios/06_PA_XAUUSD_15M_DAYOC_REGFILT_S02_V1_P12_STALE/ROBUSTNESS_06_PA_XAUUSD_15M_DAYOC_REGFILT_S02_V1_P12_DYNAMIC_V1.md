# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P12 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:39:00

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 58 |
| Win Rate | 65.5% |
| Avg Win | $235.95 |
| Avg Loss | $214.19 |
| Payoff Ratio | 1.10 |
| Expectancy / Trade | $80.73 |
| Profit Factor | 2.09 |
| Net Profit | $4,682.35 |
| Max DD (USD) | $1,604.70 |
| Recovery Factor | 2.92 |

## Section 2 — Tail Contribution

- Top 1 trade: 15.34%
- Top 5 trades: 59.86%
- Top 1% (1): 15.34%
- Top 5% (2): 30.04%
- Total PnL: $4,682.35

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 28.12%
- New CAGR: 24.04%
- Degradation: 14.51%
- New Equity: $13,963.97

**Removing Top 5% (2 trades)**
- Original CAGR: 28.12%
- New CAGR: 20.06%
- Degradation: 28.66%
- New Equity: $13,275.77

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 19
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 5, NORMAL: 8
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.26%
- Median CAGR: 0.26%
- 5th pctl CAGR: 0.02%
- 95th pctl CAGR: 0.53%
- Mean DD: 11.19%
- 95th pctl DD: 19.06%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 19.06%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.26% |
| 15.00% | 0.39% |
| 20.00% | 0.52% |
| 25.00% | 0.66% |
| 30.00% | 0.79% |

**Kelly Fraction**

- Full Kelly: 0.3421
- Safe fraction (½ Kelly): 0.1711

## Section 5 — Reverse Path Test

- Final Equity: $14,682.35
- CAGR: 28.07%
- Max DD: 12.54%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 7
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 12.55%
- Worst DD: 12.54%
- Mean return: 15.33%
- Mean DD: 12.54%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 34 | $1,188.91 | 58.8% | $34.97 |
| 2025 | 24 | $3,493.44 | 75.0% | $145.56 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|
| 2024 | +0 | +243 | +718 | +0 | -19 | +1344 | -1097 |
| 2025 | +1080 | +68 | +0 | +1817 | +529 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-08-22
- Max DD: 12.54%
- Duration: 295 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-129.09
- Max loss streak: 3

### Cluster 2
- Start: 2024-09-17
- Trough: 2024-10-08
- Recovery: 2024-10-17
- Max DD: 6.62%
- Duration: 30 days
- Trades open: 8
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 8
- Win rate: 25.0%
- Avg PnL: $-65.81
- Max loss streak: 4

### Cluster 3
- Start: 2024-10-23
- Trough: 2024-10-23
- Recovery: 2024-10-29
- Max DD: 3.16%
- Duration: 6 days
- Trades open: 0
- Long/Short: 0.0% / 0.0%
- Top-2 symbol concentration: 0.0%
- Trades closed in plunge: 0

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 5 |
| Avg Streak | 2.9 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $4,682.35 | 2.09 | 0.00% |
| Slip 1.0 pip RT | $4,617.05 | 2.07 | 1.39% |
| Spread +50% | $4,633.38 | 2.08 | 1.05% |
| Severe (1.0 + 75%) | $4,543.59 | 2.05 | 2.96% |

## Section 10 — Directional Robustness

- Total Longs: 58
- Total Shorts: 0
- Baseline PF: 2.09
- No Top-20 Longs PF: 0.46
- No Top-20 Shorts PF: 2.09
- No Both PF: 0.46

## Section 11 — Early/Late Split

**First Half** (29 trades)
- CAGR: 44.38%
- Max DD: 6.62%
- Win Rate: 65.52%

**Second Half** (29 trades)
- CAGR: 21.76%
- Max DD: 16.05%
- Win Rate: 65.52%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 58 | $4,682.35 | 65.5% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 19.81%
- Median CAGR: 19.55%
- 5th pctl CAGR: -3.83%
- 95th pctl CAGR: 46.26%
- Mean DD: 15.57%
- Worst DD: 22.82%
- Runs ending below start: 30

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 58 trades < 300 threshold
- Dispersion: max deviation 637.65 from global mean 80.73

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 153.16 from global mean 80.73
