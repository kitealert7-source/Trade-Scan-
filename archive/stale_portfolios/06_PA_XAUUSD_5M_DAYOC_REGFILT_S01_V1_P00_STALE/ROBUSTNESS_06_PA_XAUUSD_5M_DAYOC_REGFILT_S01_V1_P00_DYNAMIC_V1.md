# ROBUSTNESS REPORT — 06_PA_XAUUSD_5M_DAYOC_REGFILT_S01_V1_P00 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 13:18:00

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 64 |
| Win Rate | 59.4% |
| Avg Win | $607.10 |
| Avg Loss | $389.67 |
| Payoff Ratio | 1.56 |
| Expectancy / Trade | $202.16 |
| Profit Factor | 2.28 |
| Net Profit | $12,938.29 |
| Max DD (USD) | $3,454.87 |
| Recovery Factor | 3.74 |

## Section 2 — Tail Contribution

- Top 1 trade: 15.98%
- Top 5 trades: 61.96%
- Top 1% (1): 15.98%
- Top 5% (3): 43.68%
- Total PnL: $12,938.29

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 233.08%
- New CAGR: 190.48%
- Degradation: 18.28%
- New Equity: $20,871.19

**Removing Top 5% (3 trades)**
- Original CAGR: 233.08%
- New CAGR: 121.06%
- Degradation: 48.06%
- New Equity: $17,286.53

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 19
- Regime Distribution: HIGH_VOL: 5, LOW_VOL: 5, NORMAL: 9
- Simulations: 500
- Seed: 42

- Mean CAGR: 2.43%
- Median CAGR: 1.96%
- 5th pctl CAGR: 0.23%
- 95th pctl CAGR: 5.66%
- Mean DD: 20.35%
- 95th pctl DD: 36.05%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 36.05%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.14% |
| 15.00% | 0.21% |
| 20.00% | 0.28% |
| 25.00% | 0.35% |
| 30.00% | 0.42% |

**Kelly Fraction**

- Full Kelly: 0.3330
- Safe fraction (½ Kelly): 0.1665

## Section 5 — Reverse Path Test

- Final Equity: $22,938.29
- CAGR: 236.34%
- Max DD: 24.25%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 0
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 0.00%
- Worst DD: 0.00%
- Mean return: 0.00%
- Mean DD: 0.00%
- Negative clustering: N/A

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2025 | 64 | $12,938.29 | 59.4% | $202.16 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Jul | Aug | Sep |
|---|---|---|---|---|---|
| 2025 | +2312 | +130 | -1557 | +3816 | +8237 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-29
- Max DD: 24.25%
- Duration: 37 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-453.29
- Max loss streak: 4

### Cluster 2
- Start: 2025-09-17
- Trough: 2025-09-18
- Recovery: 2025-09-19
- Max DD: 7.08%
- Duration: 2 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-1,306.40
- Max loss streak: 1

### Cluster 3
- Start: 2025-07-14
- Trough: 2025-07-15
- Recovery: 2025-07-21
- Max DD: 5.08%
- Duration: 7 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-235.43
- Max loss streak: 1

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 4 |
| Avg Streak | 2.1 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $12,938.29 | 2.28 | 0.00% |
| Slip 1.0 pip RT | $12,792.59 | 2.26 | 1.13% |
| Spread +50% | $12,829.01 | 2.26 | 0.84% |
| Severe (1.0 + 75%) | $12,628.68 | 2.23 | 2.39% |

## Section 10 — Directional Robustness

- Total Longs: 64
- Total Shorts: 0
- Baseline PF: 2.28
- No Top-20 Longs PF: 0.41
- No Top-20 Shorts PF: 2.28
- No Both PF: 0.41

## Section 11 — Early/Late Split

**First Half** (32 trades)
- CAGR: 44.28%
- Max DD: 24.25%
- Win Rate: 59.38%

**Second Half** (32 trades)
- CAGR: 36111.37%
- Max DD: 14.48%
- Win Rate: 59.38%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 64 | $12,938.29 | 59.4% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -0.80%
- Median CAGR: -0.80%
- 5th pctl CAGR: -0.80%
- 95th pctl CAGR: -0.80%
- Mean DD: 7.19%
- Worst DD: 7.19%
- Runs ending below start: 0

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 64 trades < 300 threshold
- Dispersion: max deviation 313.41 from global mean 202.16

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 275.34 from global mean 202.16
