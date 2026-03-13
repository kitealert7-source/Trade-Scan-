# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P10 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:49

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 124 |
| Win Rate | 62.1% |
| Avg Win | $256.11 |
| Avg Loss | $210.25 |
| Payoff Ratio | 1.22 |
| Expectancy / Trade | $79.34 |
| Profit Factor | 2.00 |
| Net Profit | $9,838.52 |
| Max DD (USD) | $1,827.48 |
| Recovery Factor | 5.38 |

## Section 2 — Tail Contribution

- Top 1 trade: 9.13%
- Top 5 trades: 38.59%
- Top 1% (1): 9.13%
- Top 5% (6): 45.08%
- Total PnL: $9,838.52

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 53.03%
- New CAGR: 48.69%
- Degradation: 8.19%
- New Equity: $18,940.02

**Removing Top 5% (6 trades)**
- Original CAGR: 53.03%
- New CAGR: 30.78%
- Degradation: 41.97%
- New Equity: $15,403.58

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 16
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 5, NORMAL: 7
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.51%
- Median CAGR: 0.51%
- 5th pctl CAGR: 0.15%
- 95th pctl CAGR: 0.91%
- Mean DD: 11.97%
- 95th pctl DD: 17.84%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 17.84%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.28% |
| 15.00% | 0.42% |
| 20.00% | 0.56% |
| 25.00% | 0.70% |
| 30.00% | 0.84% |

**Kelly Fraction**

- Full Kelly: 0.3098
- Safe fraction (½ Kelly): 0.1549

## Section 5 — Reverse Path Test

- Final Equity: $19,838.52
- CAGR: 53.04%
- Max DD: 12.30%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 23.95%
- Worst DD: 12.30%
- Mean return: 31.44%
- Mean DD: 12.30%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 60 | $3,033.34 | 61.7% | $50.56 |
| 2025 | 64 | $6,805.18 | 62.5% | $106.33 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +358 | +1234 | +0 | -205 | +1136 | +1746 | -1236 |
| 2025 | +1255 | +79 | +0 | -586 | +2266 | +3791 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-07-21
- Max DD: 12.30%
- Duration: 263 days
- Trades open: 3
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 3
- Win rate: 33.3%
- Avg PnL: $-162.65
- Max loss streak: 2

### Cluster 2
- Start: 2025-07-23
- Trough: 2025-07-30
- Recovery: 2025-08-28
- Max DD: 10.64%
- Duration: 36 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-210.72
- Max loss streak: 4

### Cluster 3
- Start: 2024-02-13
- Trough: 2024-02-13
- Recovery: 2024-02-20
- Max DD: 4.48%
- Duration: 7 days
- Trades open: 0
- Long/Short: 0.0% / 0.0%
- Top-2 symbol concentration: 0.0%
- Trades closed in plunge: 0

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 4 |
| Avg Streak | 2.5 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $9,838.52 | 2.00 | 0.00% |
| Slip 1.0 pip RT | $9,684.52 | 1.97 | 1.57% |
| Spread +50% | $9,723.02 | 1.98 | 1.17% |
| Severe (1.0 + 75%) | $9,511.27 | 1.95 | 3.33% |

## Section 10 — Directional Robustness

- Total Longs: 124
- Total Shorts: 0
- Baseline PF: 2.00
- No Top-20 Longs PF: 0.90
- No Top-20 Shorts PF: 2.00
- No Both PF: 0.90

## Section 11 — Early/Late Split

**First Half** (62 trades)
- CAGR: 38.07%
- Max DD: 12.30%
- Win Rate: 62.90%

**Second Half** (62 trades)
- CAGR: 106.25%
- Max DD: 13.78%
- Win Rate: 61.29%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 124 | $9,838.52 | 62.1% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 53.60%
- Median CAGR: 52.02%
- 5th pctl CAGR: 30.20%
- 95th pctl CAGR: 81.82%
- Mean DD: 15.76%
- Worst DD: 18.46%
- Runs ending below start: 53

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 124 trades < 300 threshold
- Dispersion: max deviation 491.20 from global mean 79.34

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 161.68 from global mean 79.34
