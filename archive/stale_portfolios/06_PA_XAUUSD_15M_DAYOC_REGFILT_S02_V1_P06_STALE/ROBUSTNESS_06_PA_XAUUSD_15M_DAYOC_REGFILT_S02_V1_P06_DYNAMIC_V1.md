# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P06 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:12

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 160 |
| Win Rate | 61.9% |
| Avg Win | $306.57 |
| Avg Loss | $237.83 |
| Payoff Ratio | 1.29 |
| Expectancy / Trade | $99.02 |
| Profit Factor | 2.09 |
| Net Profit | $15,842.63 |
| Max DD (USD) | $2,329.72 |
| Recovery Factor | 6.80 |

## Section 2 — Tail Contribution

- Top 1 trade: 7.18%
- Top 5 trades: 30.24%
- Top 1% (1): 7.18%
- Top 5% (8): 44.22%
- Total PnL: $15,842.63

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 77.79%
- New CAGR: 73.00%
- Degradation: 6.15%
- New Equity: $24,704.53

**Removing Top 5% (8 trades)**
- Original CAGR: 77.79%
- New CAGR: 46.78%
- Degradation: 39.86%
- New Equity: $18,836.48

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 30
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 10, NORMAL: 14
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.71%
- Median CAGR: 0.68%
- 5th pctl CAGR: 0.31%
- 95th pctl CAGR: 1.18%
- Mean DD: 11.74%
- 95th pctl DD: 17.10%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 17.10%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.29% |
| 15.00% | 0.44% |
| 20.00% | 0.58% |
| 25.00% | 0.73% |
| 30.00% | 0.88% |

**Kelly Fraction**

- Full Kelly: 0.3230
- Safe fraction (½ Kelly): 0.1615

## Section 5 — Reverse Path Test

- Final Equity: $25,842.63
- CAGR: 78.07%
- Max DD: 13.01%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 31.70%
- Worst DD: 13.01%
- Mean return: 55.86%
- Mean DD: 13.01%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 80 | $5,579.37 | 61.3% | $69.74 |
| 2025 | 80 | $10,263.26 | 62.5% | $128.29 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | +34 | +250 | +1219 | +0 | +2345 | -63 | +1420 | +1985 | -1611 |
| 2025 | +1537 | +101 | +1360 | -79 | -948 | +3081 | +5210 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-03-28
- Max DD: 13.01%
- Duration: 148 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-184.76
- Max loss streak: 3

### Cluster 2
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-27
- Max DD: 10.74%
- Duration: 35 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-262.52
- Max loss streak: 4

### Cluster 3
- Start: 2024-02-09
- Trough: 2024-02-13
- Recovery: 2024-02-28
- Max DD: 6.89%
- Duration: 19 days
- Trades open: 2
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 0.0%
- Avg PnL: $-125.96
- Max loss streak: 2

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 5 |
| Avg Streak | 2.4 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $15,842.63 | 2.09 | 0.00% |
| Slip 1.0 pip RT | $15,608.43 | 2.07 | 1.48% |
| Spread +50% | $15,666.98 | 2.07 | 1.11% |
| Severe (1.0 + 75%) | $15,344.96 | 2.04 | 3.14% |

## Section 10 — Directional Robustness

- Total Longs: 160
- Total Shorts: 0
- Baseline PF: 2.09
- No Top-20 Longs PF: 1.10
- No Top-20 Shorts PF: 2.09
- No Both PF: 1.10

## Section 11 — Early/Late Split

**First Half** (80 trades)
- CAGR: 78.31%
- Max DD: 13.01%
- Win Rate: 61.25%

**Second Half** (80 trades)
- CAGR: 173.90%
- Max DD: 15.03%
- Win Rate: 62.50%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 160 | $15,842.63 | 61.9% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 85.14%
- Median CAGR: 85.95%
- 5th pctl CAGR: 64.25%
- 95th pctl CAGR: 106.33%
- Mean DD: 15.79%
- Worst DD: 19.54%
- Runs ending below start: 30

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 160 trades < 300 threshold
- Dispersion: max deviation 501.76 from global mean 99.02

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 164.73 from global mean 99.02
