# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P15 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 15:24:48

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 286 |
| Win Rate | 53.1% |
| Avg Win | $102.78 |
| Avg Loss | $76.76 |
| Payoff Ratio | 1.34 |
| Expectancy / Trade | $18.66 |
| Profit Factor | 1.52 |
| Net Profit | $5,336.86 |
| Max DD (USD) | $1,924.77 |
| Recovery Factor | 2.77 |

## Section 2 — Tail Contribution

- Top 1 trade: 8.88%
- Top 5 trades: 32.67%
- Top 1% (2): 15.33%
- Top 5% (14): 76.78%
- Total PnL: $5,336.86

## Section 3 — Tail Removal

**Removing Top 1% (2 trades)**
- Original CAGR: 17.03%
- New CAGR: 14.69%
- Degradation: 13.72%
- New Equity: $14,518.60

**Removing Top 5% (14 trades)**
- Original CAGR: 17.03%
- New CAGR: 4.39%
- Degradation: 74.22%
- New Equity: $11,239.46

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 30
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 10, NORMAL: 14
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.16%
- Median CAGR: 0.16%
- 5th pctl CAGR: 0.03%
- 95th pctl CAGR: 0.30%
- Mean DD: 12.77%
- 95th pctl DD: 20.26%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 20.26%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.25% |
| 15.00% | 0.37% |
| 20.00% | 0.49% |
| 25.00% | 0.62% |
| 30.00% | 0.74% |

**Kelly Fraction**

- Full Kelly: 0.1816
- Safe fraction (½ Kelly): 0.0908

## Section 5 — Reverse Path Test

- Final Equity: $15,336.86
- CAGR: 17.02%
- Max DD: 17.49%
- Max Loss Streak: 10

## Section 6 — Rolling 1-Year Window

- Total windows: 21
- Negative windows: 6
- Return < -10%: 0
- DD > 15%: 7
- DD > 20%: 0
- Worst return: -7.09%
- Worst DD: 17.49%
- Mean return: 14.50%
- Mean DD: 10.21%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2023 | 126 | $-230.43 | 42.1% | $-1.83 |
| 2024 | 80 | $2,374.15 | 61.3% | $29.68 |
| 2025 | 80 | $3,193.14 | 62.5% | $39.91 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023 | +410 | +27 | +262 | +0 | +223 | -799 | +493 | -352 | -1019 | +524 | +0 |
| 2024 | +16 | +127 | +541 | +0 | +0 | +0 | +950 | -11 | +607 | +735 | -591 |
| 2025 | +529 | +34 | +457 | -24 | +0 | +0 | -313 | +1025 | +1486 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2023-06-02
- Trough: 2023-10-05
- Recovery: 2024-07-11
- Max DD: 17.49%
- Duration: 405 days
- Trades open: 87
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 87
- Win rate: 33.3%
- Avg PnL: $-21.98
- Max loss streak: 10

### Cluster 2
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-03-28
- Max DD: 6.50%
- Duration: 148 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-64.54
- Max loss streak: 3

### Cluster 3
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-27
- Max DD: 5.34%
- Duration: 35 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-91.87
- Max loss streak: 4

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 10 |
| Avg Streak | 2.4 | 2.1 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $5,336.86 | 1.52 | 0.00% |
| Slip 1.0 pip RT | $5,149.76 | 1.50 | 3.51% |
| Spread +50% | $5,196.54 | 1.50 | 2.63% |
| Severe (1.0 + 75%) | $4,939.27 | 1.47 | 7.45% |

## Section 10 — Directional Robustness

- Total Longs: 286
- Total Shorts: 0
- Baseline PF: 1.52
- No Top-20 Longs PF: 0.99
- No Top-20 Shorts PF: 1.52
- No Both PF: 0.99

## Section 11 — Early/Late Split

**First Half** (143 trades)
- CAGR: 2.00%
- Max DD: 17.49%
- Win Rate: 44.76%

**Second Half** (143 trades)
- CAGR: 30.37%
- Max DD: 6.62%
- Win Rate: 61.54%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 286 | $5,336.86 | 53.1% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 53.70%
- Median CAGR: 55.10%
- 5th pctl CAGR: 28.93%
- 95th pctl CAGR: 85.54%
- Mean DD: 21.36%
- Worst DD: 29.56%
- Runs ending below start: 9

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 286 trades < 300 threshold
- Dispersion: max deviation 166.29 from global mean 18.66

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 42.69 from global mean 18.66
