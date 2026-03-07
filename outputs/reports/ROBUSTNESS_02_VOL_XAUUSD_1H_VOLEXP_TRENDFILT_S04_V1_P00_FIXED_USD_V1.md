# ROBUSTNESS REPORT — 02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S04_V1_P00 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 19:31:26

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 86 |
| Win Rate | 70.9% |
| Avg Win | $13.78 |
| Avg Loss | $35.26 |
| Payoff Ratio | 0.39 |
| Expectancy / Trade | $-0.48 |
| Profit Factor | 0.95 |
| Net Profit | $-41.12 |
| Max DD (USD) | $284.98 |
| Recovery Factor | -0.14 |

## Section 2 — Tail Contribution

- Top 1 trade: -143.29%
- Top 5 trades: -512.57%
- Top 1% (1): -143.29%
- Top 5% (4): -446.55%
- Total PnL: $-41.12

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: -0.21%
- New CAGR: -0.51%
- Degradation: 143.64%
- New Equity: $9,899.96

**Removing Top 5% (4 trades)**
- Original CAGR: -0.21%
- New CAGR: -1.14%
- Degradation: 449.06%
- New Equity: $9,775.26

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 23
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 8, NORMAL: 11
- Simulations: 500
- Seed: 42

- Mean CAGR: -0.00%
- Median CAGR: -0.00%
- 5th pctl CAGR: -0.02%
- 95th pctl CAGR: 0.01%
- Mean DD: 2.59%
- 95th pctl DD: 4.53%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 4.53%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 1.10% |
| 15.00% | 1.65% |
| 20.00% | 2.00% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.0000
- Safe fraction (½ Kelly): 0.0000

## Section 5 — Reverse Path Test

- Final Equity: $9,958.88
- CAGR: -0.21%
- Max DD: 2.84%
- Max Loss Streak: 3

## Section 6 — Rolling 1-Year Window

- Total windows: 13
- Negative windows: 8
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -1.83%
- Worst DD: 2.84%
- Mean return: -0.15%
- Mean DD: 1.81%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 39 | $-139.49 | 64.1% | $-3.58 |
| 2025 | 44 | $85.28 | 75.0% | $1.94 |
| 2026 | 3 | $13.09 | 100.0% | $4.36 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -46 | +28 | +30 | +3 | -63 | +17 | -20 | -4 | -180 | +38 | +15 | +43 |
| 2025 | -12 | +1 | +12 | +27 | -55 | +20 | +18 | +37 | -15 | +27 | -10 | +35 |
| 2026 | +13 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-04-08
- Trough: 2024-09-27
- Recovery: ONGOING
- Max DD: 2.84%
- Duration: 652 days
- Trades open: 23
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 23
- Win rate: 52.2%
- Avg PnL: $-11.09
- Max loss streak: 3

### Cluster 2
- Start: 2024-03-01
- Trough: 2024-03-01
- Recovery: 2024-03-05
- Max DD: 0.08%
- Duration: 4 days
- Trades open: 0
- Long/Short: 0.0% / 0.0%
- Top-2 symbol concentration: 0.0%
- Trades closed in plunge: 0

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 3 |
| Avg Streak | 3.4 | 1.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-41.12 | 0.95 | 0.00% |
| Slip 1.0 pip RT | $-64.02 | 0.93 | -55.69% |
| Spread +50% | $-58.29 | 0.93 | -41.77% |
| Severe (1.0 + 75%) | $-89.78 | 0.90 | -118.34% |

## Section 10 — Directional Robustness

- Total Longs: 86
- Total Shorts: 0
- Baseline PF: 0.95
- No Top-20 Longs PF: 0.35
- No Top-20 Shorts PF: 0.95
- No Both PF: 0.35

## Section 11 — Early/Late Split

**First Half** (43 trades)
- CAGR: -2.00%
- Max DD: 2.84%
- Win Rate: 60.47%

**Second Half** (43 trades)
- CAGR: 1.52%
- Max DD: 0.71%
- Win Rate: 81.40%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 86 | $-41.12 | 70.9% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -0.25%
- Median CAGR: -0.14%
- 5th pctl CAGR: -2.46%
- 95th pctl CAGR: 1.56%
- Mean DD: 4.72%
- Worst DD: 9.28%
- Runs ending below start: 23

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 86 trades < 300 threshold
- Dispersion: max deviation 23.89 from global mean -0.48

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 11.67 from global mean -0.48
