# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P11 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:56

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 106 |
| Win Rate | 63.2% |
| Avg Win | $269.90 |
| Avg Loss | $202.81 |
| Payoff Ratio | 1.33 |
| Expectancy / Trade | $95.98 |
| Profit Factor | 2.29 |
| Net Profit | $10,173.44 |
| Max DD (USD) | $1,995.16 |
| Recovery Factor | 5.10 |

## Section 2 — Tail Contribution

- Top 1 trade: 8.83%
- Top 5 trades: 37.46%
- Top 1% (1): 8.83%
- Top 5% (5): 37.46%
- Total PnL: $10,173.44

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 55.48%
- New CAGR: 51.09%
- Degradation: 7.92%
- New Equity: $19,274.94

**Removing Top 5% (5 trades)**
- Original CAGR: 55.48%
- New CAGR: 36.30%
- Degradation: 34.58%
- New Equity: $16,362.50

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 20
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 5, NORMAL: 9
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.51%
- Median CAGR: 0.48%
- 5th pctl CAGR: 0.11%
- 95th pctl CAGR: 0.93%
- Mean DD: 12.89%
- 95th pctl DD: 22.03%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 22.03%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.23% |
| 15.00% | 0.34% |
| 20.00% | 0.45% |
| 25.00% | 0.57% |
| 30.00% | 0.68% |

**Kelly Fraction**

- Full Kelly: 0.3556
- Safe fraction (½ Kelly): 0.1778

## Section 5 — Reverse Path Test

- Final Equity: $20,173.44
- CAGR: 55.45%
- Max DD: 13.27%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 23.21%
- Worst DD: 13.27%
- Mean return: 29.44%
- Mean DD: 13.27%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 54 | $3,036.57 | 59.3% | $56.23 |
| 2025 | 52 | $7,136.87 | 67.3% | $137.25 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +556 | +1091 | +0 | +0 | +1073 | +1678 | -1361 |
| 2025 | +1267 | +79 | +0 | -630 | +2365 | +4056 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-08-26
- Max DD: 13.27%
- Duration: 299 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-163.91
- Max loss streak: 3

### Cluster 2
- Start: 2024-09-27
- Trough: 2024-10-09
- Recovery: 2024-10-15
- Max DD: 4.98%
- Duration: 18 days
- Trades open: 7
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 7
- Win rate: 14.3%
- Avg PnL: $-78.02
- Max loss streak: 4

### Cluster 3
- Start: 2024-10-23
- Trough: 2024-10-23
- Recovery: 2024-10-29
- Max DD: 3.36%
- Duration: 6 days
- Trades open: 0
- Long/Short: 0.0% / 0.0%
- Top-2 symbol concentration: 0.0%
- Trades closed in plunge: 0

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 5 |
| Avg Streak | 2.3 | 1.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $10,173.44 | 2.29 | 0.00% |
| Slip 1.0 pip RT | $10,039.34 | 2.26 | 1.32% |
| Spread +50% | $10,072.86 | 2.27 | 0.99% |
| Severe (1.0 + 75%) | $9,888.48 | 2.23 | 2.80% |

## Section 10 — Directional Robustness

- Total Longs: 106
- Total Shorts: 0
- Baseline PF: 2.29
- No Top-20 Longs PF: 0.96
- No Top-20 Shorts PF: 2.29
- No Both PF: 0.96

## Section 11 — Early/Late Split

**First Half** (53 trades)
- CAGR: 66.84%
- Max DD: 5.09%
- Win Rate: 60.38%

**Second Half** (53 trades)
- CAGR: 68.25%
- Max DD: 13.40%
- Win Rate: 66.04%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 106 | $10,173.44 | 63.2% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 54.46%
- Median CAGR: 53.62%
- 5th pctl CAGR: 23.91%
- 95th pctl CAGR: 89.23%
- Mean DD: 14.16%
- Worst DD: 19.48%
- Runs ending below start: 53

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 106 trades < 300 threshold
- Dispersion: max deviation 726.34 from global mean 95.98

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 167.99 from global mean 95.98
