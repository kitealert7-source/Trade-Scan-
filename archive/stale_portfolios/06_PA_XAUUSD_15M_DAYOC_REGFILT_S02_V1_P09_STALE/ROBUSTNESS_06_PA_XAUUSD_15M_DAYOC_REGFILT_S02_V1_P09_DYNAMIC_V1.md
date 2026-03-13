# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P09 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:42

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 151 |
| Win Rate | 60.9% |
| Avg Win | $273.33 |
| Avg Loss | $232.04 |
| Payoff Ratio | 1.18 |
| Expectancy / Trade | $75.87 |
| Profit Factor | 1.84 |
| Net Profit | $11,455.78 |
| Max DD (USD) | $2,204.30 |
| Recovery Factor | 5.20 |

## Section 2 — Tail Contribution

- Top 1 trade: 8.01%
- Top 5 trades: 34.04%
- Top 1% (1): 8.01%
- Top 5% (7): 46.00%
- Total PnL: $11,455.78

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 59.28%
- New CAGR: 55.09%
- Degradation: 7.07%
- New Equity: $20,538.18

**Removing Top 5% (7 trades)**
- Original CAGR: 59.28%
- New CAGR: 34.13%
- Degradation: 42.43%
- New Equity: $16,186.11

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 19
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 7, NORMAL: 8
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.52%
- Median CAGR: 0.50%
- 5th pctl CAGR: 0.18%
- 95th pctl CAGR: 0.89%
- Mean DD: 13.12%
- 95th pctl DD: 18.86%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 18.86%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.27% |
| 15.00% | 0.40% |
| 20.00% | 0.53% |
| 25.00% | 0.66% |
| 30.00% | 0.80% |

**Kelly Fraction**

- Full Kelly: 0.2776
- Safe fraction (½ Kelly): 0.1388

## Section 5 — Reverse Path Test

- Final Equity: $21,455.78
- CAGR: 59.41%
- Max DD: 13.06%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 17.53%
- Worst DD: 13.06%
- Mean return: 39.12%
- Mean DD: 13.06%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 76 | $4,668.94 | 60.5% | $61.43 |
| 2025 | 75 | $6,786.84 | 61.3% | $90.49 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jun | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | +77 | +213 | +1219 | +83 | +2019 | +0 | +786 | +1798 | -1528 |
| 2025 | +1389 | +90 | +0 | -343 | -222 | +2700 | +3173 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-07-22
- Max DD: 13.06%
- Duration: 264 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-174.34
- Max loss streak: 3

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
- Avg PnL: $-232.38
- Max loss streak: 4

### Cluster 3
- Start: 2024-02-08
- Trough: 2024-02-13
- Recovery: 2024-02-29
- Max DD: 7.23%
- Duration: 21 days
- Trades open: 3
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 3
- Win rate: 0.0%
- Avg PnL: $-96.45
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 4 |
| Avg Streak | 2.4 | 1.6 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $11,455.78 | 1.84 | 0.00% |
| Slip 1.0 pip RT | $11,248.68 | 1.82 | 1.81% |
| Spread +50% | $11,300.45 | 1.82 | 1.36% |
| Severe (1.0 + 75%) | $11,015.69 | 1.79 | 3.84% |

## Section 10 — Directional Robustness

- Total Longs: 151
- Total Shorts: 0
- Baseline PF: 1.84
- No Top-20 Longs PF: 0.93
- No Top-20 Shorts PF: 1.84
- No Both PF: 0.93

## Section 11 — Early/Late Split

**First Half** (75 trades)
- CAGR: 87.27%
- Max DD: 7.23%
- Win Rate: 61.33%

**Second Half** (76 trades)
- CAGR: 62.98%
- Max DD: 16.52%
- Win Rate: 60.53%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 151 | $11,455.78 | 60.9% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 58.75%
- Median CAGR: 60.00%
- 5th pctl CAGR: 48.82%
- 95th pctl CAGR: 67.34%
- Mean DD: 16.76%
- Worst DD: 19.47%
- Runs ending below start: 30

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 151 trades < 300 threshold
- Dispersion: max deviation 457.82 from global mean 75.87

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 143.96 from global mean 75.87
