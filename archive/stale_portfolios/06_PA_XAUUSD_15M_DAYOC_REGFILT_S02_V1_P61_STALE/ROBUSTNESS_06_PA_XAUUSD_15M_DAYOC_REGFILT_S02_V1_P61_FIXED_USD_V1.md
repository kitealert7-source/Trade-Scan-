# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P61 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-10 11:29:06

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 160 |
| Win Rate | 29.4% |
| Avg Win | $194.70 |
| Avg Loss | $46.33 |
| Payoff Ratio | 4.20 |
| Expectancy / Trade | $24.47 |
| Profit Factor | 1.75 |
| Net Profit | $3,915.92 |
| Max DD (USD) | $1,132.56 |
| Recovery Factor | 3.46 |

## Section 2 — Tail Contribution

- Top 1 trade: 13.22%
- Top 5 trades: 57.36%
- Top 1% (1): 13.22%
- Top 5% (8): 85.18%
- Total PnL: $3,915.92

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 22.17%
- New CAGR: 19.40%
- Degradation: 12.52%
- New Equity: $13,398.24

**Removing Top 5% (8 trades)**
- Original CAGR: 22.17%
- New CAGR: 3.48%
- Degradation: 84.31%
- New Equity: $10,580.32

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 17
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 5, NORMAL: 8
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.21%
- Median CAGR: 0.20%
- 5th pctl CAGR: 0.08%
- 95th pctl CAGR: 0.37%
- Mean DD: 5.77%
- 95th pctl DD: 8.73%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 8.73%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.57% |
| 15.00% | 0.86% |
| 20.00% | 1.15% |
| 25.00% | 1.43% |
| 30.00% | 1.72% |

**Kelly Fraction**

- Full Kelly: 0.1257
- Safe fraction (½ Kelly): 0.0629

## Section 5 — Reverse Path Test

- Final Equity: $13,915.92
- CAGR: 22.24%
- Max DD: 7.98%
- Max Loss Streak: 12

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 22.87%
- Worst DD: 6.99%
- Mean return: 36.09%
- Mean DD: 4.11%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 80 | $2,838.06 | 32.5% | $35.48 |
| 2025 | 80 | $1,077.86 | 26.2% | $13.47 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | -49 | -181 | +56 | +0 | +920 | +101 | +752 | +1386 | -146 |
| 2025 | +572 | -46 | +501 | -48 | +269 | -929 | +758 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-07-22
- Trough: 2025-09-02
- Recovery: ONGOING
- Max DD: 7.98%
- Duration: 63 days
- Trades open: 30
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 30
- Win rate: 10.0%
- Avg PnL: $-36.21
- Max loss streak: 11

### Cluster 2
- Start: 2024-02-21
- Trough: 2024-03-04
- Recovery: 2024-07-11
- Max DD: 3.97%
- Duration: 141 days
- Trades open: 8
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 8
- Win rate: 0.0%
- Avg PnL: $-43.93
- Max loss streak: 8

### Cluster 3
- Start: 2024-10-31
- Trough: 2025-01-20
- Recovery: 2025-01-24
- Max DD: 3.65%
- Duration: 85 days
- Trades open: 10
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 10
- Win rate: 0.0%
- Avg PnL: $-42.94
- Max loss streak: 10

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 3 | 12 |
| Avg Streak | 1.4 | 3.3 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $3,915.92 | 1.75 | 0.00% |
| Slip 1.0 pip RT | $3,767.22 | 1.71 | 3.80% |
| Spread +50% | $3,804.39 | 1.72 | 2.85% |
| Severe (1.0 + 75%) | $3,599.93 | 1.66 | 8.07% |

## Section 10 — Directional Robustness

- Total Longs: 160
- Total Shorts: 0
- Baseline PF: 1.75
- No Top-20 Longs PF: 0.54
- No Top-20 Shorts PF: 1.75
- No Both PF: 0.54

## Section 11 — Early/Late Split

**First Half** (80 trades)
- CAGR: 38.53%
- Max DD: 3.97%
- Win Rate: 32.50%

**Second Half** (80 trades)
- CAGR: 15.73%
- Max DD: 9.97%
- Win Rate: 26.25%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 160 | $3,915.92 | 29.4% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 45.92%
- Median CAGR: 48.29%
- 5th pctl CAGR: 27.77%
- 95th pctl CAGR: 63.37%
- Mean DD: 9.19%
- Worst DD: 13.08%
- Runs ending below start: 27

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 160 trades < 300 threshold
- Dispersion: max deviation 72.00 from global mean 24.47

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 29.60 from global mean 24.47
