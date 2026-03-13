# ROBUSTNESS REPORT — 07_MR_XAUUSD_15M_SMI_SMIFILT_S02_V1_P03 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-09 13:44:32

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 30 |
| Win Rate | 66.7% |
| Avg Win | $36.51 |
| Avg Loss | $47.06 |
| Payoff Ratio | 0.78 |
| Expectancy / Trade | $8.65 |
| Profit Factor | 1.55 |
| Net Profit | $259.54 |
| Max DD (USD) | $256.80 |
| Recovery Factor | 1.01 |

## Section 2 — Tail Contribution

- Top 1 trade: 55.15%
- Top 5 trades: 159.50%
- Top 1% (1): 55.15%
- Top 5% (1): 55.15%
- Total PnL: $259.54

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 1.36%
- New CAGR: 0.61%
- Degradation: 55.00%
- New Equity: $10,116.41

**Removing Top 5% (1 trades)**
- Original CAGR: 1.36%
- New CAGR: 0.61%
- Degradation: 55.00%
- New Equity: $10,116.41

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 11
- Regime Distribution: HIGH_VOL: 3, LOW_VOL: 3, NORMAL: 5
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.01%
- Median CAGR: 0.01%
- 5th pctl CAGR: -0.02%
- 95th pctl CAGR: 0.04%
- Mean DD: 2.54%
- 95th pctl DD: 5.17%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 5.17%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.97% |
| 15.00% | 1.45% |
| 20.00% | 1.93% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.2370
- Safe fraction (½ Kelly): 0.1185

## Section 5 — Reverse Path Test

- Final Equity: $10,259.54
- CAGR: 1.37%
- Max DD: 2.55%
- Max Loss Streak: 2

## Section 6 — Rolling 1-Year Window

- Total windows: 11
- Negative windows: 7
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -1.74%
- Worst DD: 2.55%
- Mean return: -0.04%
- Mean DD: 2.19%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 16 | $-150.15 | 62.5% | $-9.38 |
| 2025 | 13 | $378.66 | 69.2% | $29.13 |
| 2026 | 1 | $31.03 | 100.0% | $31.03 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +7 | -81 | +46 | +37 | +0 | +25 | +0 | +33 | -254 | +36 |
| 2025 | -17 | +0 | +0 | +8 | -5 | +29 | +90 | +185 | +0 | +20 | +69 |
| 2026 | +31 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-10-23
- Trough: 2024-11-11
- Recovery: 2025-08-22
- Max DD: 2.55%
- Duration: 303 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-2.32
- Max loss streak: 1

### Cluster 2
- Start: 2024-03-12
- Trough: 2024-03-14
- Recovery: 2024-10-03
- Max DD: 1.31%
- Duration: 205 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-64.89
- Max loss streak: 1

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 6 | 2 |
| Avg Streak | 2.9 | 1.7 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $259.54 | 1.55 | 0.00% |
| Slip 1.0 pip RT | $248.94 | 1.53 | 4.08% |
| Spread +50% | $251.59 | 1.53 | 3.06% |
| Severe (1.0 + 75%) | $237.01 | 1.50 | 8.68% |

## Section 10 — Directional Robustness

- Total Longs: 30
- Total Shorts: 0
- Baseline PF: 1.55
- No Top-20 Longs PF: 0.00
- No Top-20 Shorts PF: 1.55
- No Both PF: 0.00

## Section 11 — Early/Late Split

**First Half** (15 trades)
- CAGR: -1.36%
- Max DD: 2.55%
- Win Rate: 66.67%

**Second Half** (15 trades)
- CAGR: 3.60%
- Max DD: 0.57%
- Win Rate: 66.67%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 30 | $259.54 | 66.7% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 2.83%
- Median CAGR: 3.20%
- 5th pctl CAGR: -5.05%
- 95th pctl CAGR: 10.50%
- Mean DD: 8.35%
- Worst DD: 18.11%
- Runs ending below start: 28

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 30 trades < 300 threshold
- Dispersion: max deviation 125.73 from global mean 8.65

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 61.10 from global mean 8.65
