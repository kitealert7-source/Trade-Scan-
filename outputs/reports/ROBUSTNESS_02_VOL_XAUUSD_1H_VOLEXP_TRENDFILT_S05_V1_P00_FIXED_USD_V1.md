# ROBUSTNESS REPORT — 02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S05_V1_P00 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 19:31:34

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 85 |
| Win Rate | 70.6% |
| Avg Win | $13.16 |
| Avg Loss | $33.68 |
| Payoff Ratio | 0.39 |
| Expectancy / Trade | $-0.62 |
| Profit Factor | 0.94 |
| Net Profit | $-52.52 |
| Max DD (USD) | $375.95 |
| Recovery Factor | -0.14 |

## Section 2 — Tail Contribution

- Top 1 trade: -117.82%
- Top 5 trades: -389.45%
- Top 1% (1): -117.82%
- Top 5% (4): -337.76%
- Total PnL: $-52.52

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: -0.27%
- New CAGR: -0.58%
- Degradation: 118.16%
- New Equity: $9,885.60

**Removing Top 5% (4 trades)**
- Original CAGR: -0.27%
- New CAGR: -1.17%
- Degradation: 339.70%
- New Equity: $9,770.09

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 16
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 5, NORMAL: 7
- Simulations: 500
- Seed: 42

- Mean CAGR: -0.00%
- Median CAGR: -0.00%
- 5th pctl CAGR: -0.03%
- 95th pctl CAGR: 0.02%
- Mean DD: 3.38%
- 95th pctl DD: 6.88%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 6.88%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.73% |
| 15.00% | 1.09% |
| 20.00% | 1.45% |
| 25.00% | 1.82% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.0000
- Safe fraction (½ Kelly): 0.0000

## Section 5 — Reverse Path Test

- Final Equity: $9,947.48
- CAGR: -0.27%
- Max DD: 3.74%
- Max Loss Streak: 3

## Section 6 — Rolling 1-Year Window

- Total windows: 13
- Negative windows: 8
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -2.74%
- Worst DD: 3.74%
- Mean return: -0.30%
- Mean DD: 2.15%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 39 | $-256.73 | 64.1% | $-6.58 |
| 2025 | 43 | $191.12 | 74.4% | $4.44 |
| 2026 | 3 | $13.09 | 100.0% | $4.36 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -38 | +28 | +14 | +2 | -99 | +13 | -21 | -81 | -154 | +34 | +11 | +34 |
| 2025 | +12 | +10 | -3 | +27 | -28 | -1 | +18 | +15 | +32 | +27 | +46 | +35 |
| 2026 | +13 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-04-08
- Trough: 2024-09-27
- Recovery: ONGOING
- Max DD: 3.74%
- Duration: 652 days
- Trades open: 23
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 23
- Win rate: 52.2%
- Avg PnL: $-15.05
- Max loss streak: 3

### Cluster 2
- Start: 2024-03-01
- Trough: 2024-03-01
- Recovery: 2024-03-08
- Max DD: 0.20%
- Duration: 7 days
- Trades open: 0
- Long/Short: 0.0% / 0.0%
- Top-2 symbol concentration: 0.0%
- Trades closed in plunge: 0

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 12 | 3 |
| Avg Streak | 3.5 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-52.52 | 0.94 | 0.00% |
| Slip 1.0 pip RT | $-73.02 | 0.91 | -39.03% |
| Spread +50% | $-67.90 | 0.92 | -29.27% |
| Severe (1.0 + 75%) | $-96.08 | 0.89 | -82.94% |

## Section 10 — Directional Robustness

- Total Longs: 85
- Total Shorts: 0
- Baseline PF: 0.94
- No Top-20 Longs PF: 0.33
- No Top-20 Shorts PF: 0.94
- No Both PF: 0.33

## Section 11 — Early/Late Split

**First Half** (42 trades)
- CAGR: -2.74%
- Max DD: 3.74%
- Win Rate: 61.90%

**Second Half** (43 trades)
- CAGR: 2.07%
- Max DD: 0.61%
- Win Rate: 79.07%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 85 | $-52.52 | 70.6% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -0.63%
- Median CAGR: -0.39%
- 5th pctl CAGR: -4.02%
- 95th pctl CAGR: 2.27%
- Mean DD: 6.09%
- Worst DD: 13.34%
- Runs ending below start: 23

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 85 trades < 300 threshold
- Dispersion: max deviation 17.87 from global mean -0.62

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 9.31 from global mean -0.62
