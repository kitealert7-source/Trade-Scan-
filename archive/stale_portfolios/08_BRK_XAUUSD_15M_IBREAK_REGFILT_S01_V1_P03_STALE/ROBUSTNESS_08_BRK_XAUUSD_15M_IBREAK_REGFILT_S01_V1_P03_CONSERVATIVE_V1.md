# ROBUSTNESS REPORT — 08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1_P03 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-09 18:28:13

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 177 |
| Win Rate | 52.5% |
| Avg Win | $24.02 |
| Avg Loss | $21.45 |
| Payoff Ratio | 1.12 |
| Expectancy / Trade | $2.44 |
| Profit Factor | 1.24 |
| Net Profit | $432.54 |
| Max DD (USD) | $228.43 |
| Recovery Factor | 1.89 |

## Section 2 — Tail Contribution

- Top 1 trade: 33.13%
- Top 5 trades: 118.27%
- Top 1% (1): 33.13%
- Top 5% (8): 161.15%
- Total PnL: $432.54

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 2.18%
- New CAGR: 1.47%
- Degradation: 32.90%
- New Equity: $10,289.24

**Removing Top 5% (8 trades)**
- Original CAGR: 2.18%
- New CAGR: -1.36%
- Degradation: 162.19%
- New Equity: $9,735.51

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 20
- Regime Distribution: HIGH_VOL: 5, LOW_VOL: 6, NORMAL: 9
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.02%
- Median CAGR: 0.02%
- 5th pctl CAGR: -0.02%
- 95th pctl CAGR: 0.07%
- Mean DD: 3.71%
- 95th pctl DD: 6.27%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 6.27%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.80% |
| 15.00% | 1.20% |
| 20.00% | 1.60% |
| 25.00% | 1.99% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.1017
- Safe fraction (½ Kelly): 0.0509

## Section 5 — Reverse Path Test

- Final Equity: $10,432.54
- CAGR: 2.19%
- Max DD: 2.34%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 12
- Negative windows: 2
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -0.76%
- Worst DD: 2.23%
- Mean return: 1.89%
- Mean DD: 1.94%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 143 | $511.45 | 53.1% | $3.58 |
| 2025 | 34 | $-78.91 | 50.0% | $-2.32 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -83 | -77 | +369 | -76 | +111 | +219 | +92 | -20 | -40 | -12 | +7 | +21 |
| 2025 | -81 | +4 | +31 | +0 | +0 | +14 | -4 | +28 | +6 | -17 | +0 | -59 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-03-21
- Trough: 2024-05-03
- Recovery: 2024-06-07
- Max DD: 2.23%
- Duration: 78 days
- Trades open: 16
- Long/Short: 56.2% / 43.8%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 16
- Win rate: 31.2%
- Avg PnL: $-13.29
- Max loss streak: 5

### Cluster 2
- Start: 2024-01-30
- Trough: 2024-02-16
- Recovery: 2024-03-04
- Max DD: 2.01%
- Duration: 34 days
- Trades open: 14
- Long/Short: 42.9% / 57.1%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 14
- Win rate: 42.9%
- Avg PnL: $-9.57
- Max loss streak: 3

### Cluster 3
- Start: 2024-09-17
- Trough: 2025-02-06
- Recovery: ONGOING
- Max DD: 1.82%
- Duration: 457 days
- Trades open: 41
- Long/Short: 46.3% / 53.7%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 41
- Win rate: 48.8%
- Avg PnL: $-3.95
- Max loss streak: 5

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 10 | 5 |
| Avg Streak | 2.3 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $432.54 | 1.24 | 0.00% |
| Slip 1.0 pip RT | $379.84 | 1.21 | 12.18% |
| Spread +50% | $393.01 | 1.22 | 9.14% |
| Severe (1.0 + 75%) | $320.55 | 1.17 | 25.89% |

## Section 10 — Directional Robustness

- Total Longs: 98
- Total Shorts: 79
- Baseline PF: 1.24
- No Top-20 Longs PF: 0.62
- No Top-20 Shorts PF: 0.90
- No Both PF: 0.28

## Section 11 — Early/Late Split

**First Half** (88 trades)
- CAGR: 5.37%
- Max DD: 2.34%
- Win Rate: 51.14%

**Second Half** (89 trades)
- CAGR: 1.26%
- Max DD: 1.86%
- Win Rate: 53.93%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 177 | $432.54 | 52.5% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 6.71%
- Median CAGR: 6.22%
- 5th pctl CAGR: -3.58%
- 95th pctl CAGR: 16.85%
- Mean DD: 8.07%
- Worst DD: 9.30%
- Runs ending below start: 27

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 177 trades < 300 threshold
- Dispersion: max deviation 15.45 from global mean 2.44

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 10.64 from global mean 2.44
