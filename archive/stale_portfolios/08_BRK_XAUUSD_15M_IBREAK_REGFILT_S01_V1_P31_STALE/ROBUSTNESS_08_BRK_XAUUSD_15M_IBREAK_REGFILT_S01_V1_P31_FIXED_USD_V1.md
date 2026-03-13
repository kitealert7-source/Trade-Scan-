# ROBUSTNESS REPORT — 08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1_P31 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-10 11:29:22

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 124 |
| Win Rate | 47.6% |
| Avg Win | $43.75 |
| Avg Loss | $37.30 |
| Payoff Ratio | 1.17 |
| Expectancy / Trade | $1.26 |
| Profit Factor | 1.06 |
| Net Profit | $156.73 |
| Max DD (USD) | $484.91 |
| Recovery Factor | 0.32 |

## Section 2 — Tail Contribution

- Top 1 trade: 174.34%
- Top 5 trades: 472.88%
- Top 1% (1): 174.34%
- Top 5% (6): 533.50%
- Total PnL: $156.73

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 0.73%
- New CAGR: -0.55%
- Degradation: 174.88%
- New Equity: $9,883.49

**Removing Top 5% (6 trades)**
- Original CAGR: 0.73%
- New CAGR: -3.25%
- Degradation: 543.42%
- New Equity: $9,320.58

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 14
- Regime Distribution: HIGH_VOL: 2, LOW_VOL: 6, NORMAL: 6
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.01%
- Median CAGR: 0.01%
- 5th pctl CAGR: -0.03%
- 95th pctl CAGR: 0.06%
- Mean DD: 5.28%
- 95th pctl DD: 9.47%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 9.47%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.53% |
| 15.00% | 0.79% |
| 20.00% | 1.06% |
| 25.00% | 1.32% |
| 30.00% | 1.58% |

**Kelly Fraction**

- Full Kelly: 0.0289
- Safe fraction (½ Kelly): 0.0144

## Section 5 — Reverse Path Test

- Final Equity: $10,156.73
- CAGR: 0.73%
- Max DD: 4.76%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 3
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -1.57%
- Worst DD: 4.76%
- Mean return: 1.21%
- Mean DD: 3.22%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 95 | $148.75 | 47.4% | $1.57 |
| 2025 | 27 | $-61.20 | 44.4% | $-2.27 |
| 2026 | 2 | $69.18 | 100.0% | $34.59 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -47 | +51 | +20 | -115 | -59 | +321 | +166 | -117 | -151 | -57 | -10 | +146 |
| 2025 | -41 | +21 | +55 | -10 | +0 | +41 | -41 | +56 | +12 | -27 | +0 | -128 |
| 2026 | +0 | +69 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-03-15
- Trough: 2024-05-15
- Recovery: 2024-07-05
- Max DD: 4.76%
- Duration: 112 days
- Trades open: 15
- Long/Short: 46.7% / 53.3%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 15
- Win rate: 13.3%
- Avg PnL: $-31.06
- Max loss streak: 5

### Cluster 2
- Start: 2024-08-15
- Trough: 2024-10-07
- Recovery: ONGOING
- Max DD: 4.19%
- Duration: 554 days
- Trades open: 22
- Long/Short: 50.0% / 50.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 22
- Win rate: 27.3%
- Avg PnL: $-19.63
- Max loss streak: 4

### Cluster 3
- Start: 2024-02-14
- Trough: 2024-02-22
- Recovery: 2024-03-08
- Max DD: 1.61%
- Duration: 23 days
- Trades open: 3
- Long/Short: 33.3% / 66.7%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 3
- Win rate: 0.0%
- Avg PnL: $-46.87
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 7 | 5 |
| Avg Streak | 2.2 | 2.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $156.73 | 1.06 | 0.00% |
| Slip 1.0 pip RT | $82.13 | 1.03 | 47.60% |
| Spread +50% | $100.78 | 1.04 | 35.70% |
| Severe (1.0 + 75%) | $-1.80 | 1.00 | 101.15% |

## Section 10 — Directional Robustness

- Total Longs: 64
- Total Shorts: 60
- Baseline PF: 1.06
- No Top-20 Longs PF: 0.59
- No Top-20 Shorts PF: 0.54
- No Both PF: 0.07

## Section 11 — Early/Late Split

**First Half** (62 trades)
- CAGR: 4.76%
- Max DD: 4.76%
- Win Rate: 50.00%

**Second Half** (62 trades)
- CAGR: -0.88%
- Max DD: 3.86%
- Win Rate: 45.16%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 124 | $156.73 | 47.6% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 1.43%
- Median CAGR: 1.41%
- 5th pctl CAGR: -0.32%
- 95th pctl CAGR: 3.63%
- Mean DD: 6.33%
- Worst DD: 7.33%
- Runs ending below start: 65

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 124 trades < 300 threshold
- Dispersion: max deviation 43.91 from global mean 1.26

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 15.69 from global mean 1.26
