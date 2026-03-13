# ROBUSTNESS REPORT — 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P05 / DYNAMIC_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-08 14:38:03

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 137 |
| Win Rate | 63.5% |
| Avg Win | $303.80 |
| Avg Loss | $242.95 |
| Payoff Ratio | 1.25 |
| Expectancy / Trade | $104.26 |
| Profit Factor | 2.18 |
| Net Profit | $14,283.34 |
| Max DD (USD) | $2,120.58 |
| Recovery Factor | 6.74 |

## Section 2 — Tail Contribution

- Top 1 trade: 7.55%
- Top 5 trades: 31.61%
- Top 1% (1): 7.55%
- Top 5% (6): 36.84%
- Total PnL: $14,283.34

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 71.21%
- New CAGR: 66.56%
- Degradation: 6.53%
- New Equity: $23,205.14

**Removing Top 5% (6 trades)**
- Original CAGR: 71.21%
- New CAGR: 47.65%
- Degradation: 33.08%
- New Equity: $19,021.14

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 26
- Regime Distribution: HIGH_VOL: 6, LOW_VOL: 8, NORMAL: 12
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.66%
- Median CAGR: 0.64%
- 5th pctl CAGR: 0.30%
- 95th pctl CAGR: 1.05%
- Mean DD: 10.35%
- 95th pctl DD: 13.60%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 13.60%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.37% |
| 15.00% | 0.55% |
| 20.00% | 0.74% |
| 25.00% | 0.92% |
| 30.00% | 1.10% |

**Kelly Fraction**

- Full Kelly: 0.3432
- Safe fraction (½ Kelly): 0.1716

## Section 5 — Reverse Path Test

- Final Equity: $24,283.34
- CAGR: 71.62%
- Max DD: 12.67%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 8
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 33.70%
- Worst DD: 12.67%
- Mean return: 47.80%
- Mean DD: 12.67%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 65 | $4,614.08 | 63.1% | $70.99 |
| 2025 | 72 | $9,669.26 | 63.9% | $134.30 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|
| 2024 | +34 | +358 | +1234 | +1408 | -242 | +1262 | +2005 | -1444 |
| 2025 | +1389 | +90 | +1296 | -598 | +2863 | +4629 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-31
- Trough: 2024-11-06
- Recovery: 2025-03-28
- Max DD: 12.67%
- Duration: 148 days
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
- Max DD: 10.66%
- Duration: 35 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 20.0%
- Avg PnL: $-251.16
- Max loss streak: 4

### Cluster 3
- Start: 2024-02-12
- Trough: 2024-02-13
- Recovery: 2024-02-21
- Max DD: 5.22%
- Duration: 9 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-79.20
- Max loss streak: 1

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 4 |
| Avg Streak | 2.6 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $14,283.34 | 2.18 | 0.00% |
| Slip 1.0 pip RT | $14,088.74 | 2.15 | 1.36% |
| Spread +50% | $14,137.39 | 2.16 | 1.02% |
| Severe (1.0 + 75%) | $13,869.82 | 2.13 | 2.90% |

## Section 10 — Directional Robustness

- Total Longs: 137
- Total Shorts: 0
- Baseline PF: 2.18
- No Top-20 Longs PF: 1.06
- No Top-20 Shorts PF: 2.18
- No Both PF: 1.06

## Section 11 — Early/Late Split

**First Half** (68 trades)
- CAGR: 51.75%
- Max DD: 12.67%
- Win Rate: 63.24%

**Second Half** (69 trades)
- CAGR: 167.25%
- Max DD: 14.50%
- Win Rate: 63.77%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 137 | $14,283.34 | 63.5% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 73.84%
- Median CAGR: 73.80%
- 5th pctl CAGR: 41.09%
- 95th pctl CAGR: 109.70%
- Mean DD: 15.93%
- Worst DD: 19.50%
- Runs ending below start: 30

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 137 trades < 300 threshold
- Dispersion: max deviation 465.28 from global mean 104.26

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 182.78 from global mean 104.26
