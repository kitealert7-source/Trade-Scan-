# ROBUSTNESS REPORT — ORB_FX_02 / AGGRESSIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-26 20:10:19

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 520 |
| Win Rate | 47.5% |
| Avg Win | $93.46 |
| Avg Loss | $92.67 |
| Payoff Ratio | 1.01 |
| Expectancy / Trade | $-4.26 |
| Profit Factor | 0.91 |
| Net Profit | $-2,214.63 |
| Max DD (USD) | $3,402.66 |
| Recovery Factor | -0.65 |

## Section 2 — Tail Contribution

- Top 1 trade: -19.69%
- Top 5 trades: -86.81%
- Top 1% (5): -86.81%
- Top 5% (26): -335.20%
- Total PnL: $-2,214.63

## Section 3 — Tail Removal

**Removing Top 1% (5 trades)**
- Original CAGR: -11.34%
- New CAGR: -22.64%
- Degradation: 99.66%
- New Equity: $5,862.87

**Removing Top 5% (26 trades)**
- Original CAGR: -11.34%
- New CAGR: -79.72%
- Degradation: 603.06%
- New Equity: $361.89

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.11%
- Median CAGR: -0.11%
- 5th pctl CAGR: -0.11%
- 95th pctl CAGR: -0.11%
- Mean DD: 37.37%
- 95th pctl DD: 47.12%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $7,814.44
- CAGR: -11.18%
- Max DD: 31.28%
- Max Loss Streak: 12

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 7
- Return < -10%: 2
- DD > 15%: 13
- DD > 20%: 10
- Worst return: -16.77%
- Worst DD: 31.48%
- Mean return: -1.85%
- Mean DD: 22.43%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 225 | $-1,358.07 | 46.7% | $-6.04 |
| 2025 | 262 | $-462.15 | 48.5% | $-1.76 |
| 2026 | 33 | $-394.41 | 45.5% | $-11.95 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +4 | -895 | -126 | -199 | -55 | -185 | +113 | -527 | -89 | -54 | +264 | +392 |
| 2025 | -340 | +282 | +736 | -640 | -107 | +250 | -132 | -165 | +494 | -869 | -186 | +214 |
| 2026 | -378 | -16 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-04-07
- Trough: 2026-02-04
- Recovery: ONGOING
- Max DD: 31.48%
- Duration: 312 days
- Trades open: 220
- Long/Short: 54.5% / 45.5%
- Top-2 symbol concentration: 64.5%
- Trades closed in plunge: 220
- Win rate: 44.5%
- Avg PnL: $-14.55
- Max loss streak: 11

### Cluster 2
- Start: 2024-01-18
- Trough: 2024-09-18
- Recovery: 2025-04-04
- Max DD: 23.09%
- Duration: 442 days
- Trades open: 149
- Long/Short: 51.7% / 48.3%
- Top-2 symbol concentration: 81.2%
- Trades closed in plunge: 149
- Win rate: 43.0%
- Avg PnL: $-15.78
- Max loss streak: 9

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 12 |
| Avg Streak | 2.2 | 2.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-2,214.63 | 0.91 | 0.00% |
| Slip 1.0 pip RT | $-4,473.83 | 0.83 | -102.01% |
| Spread +50% | $-3,751.39 | 0.86 | -69.39% |
| Severe (1.0 + 75%) | $-6,778.97 | 0.76 | -206.10% |

## Section 10 — Directional Robustness

- Total Longs: 277
- Total Shorts: 243
- Baseline PF: 0.91
- No Top-20 Longs PF: 0.73
- No Top-20 Shorts PF: 0.70
- No Both PF: 0.52

## Section 11 — Early/Late Split

**First Half** (260 trades)
- CAGR: -14.02%
- Max DD: 23.09%
- Win Rate: 45.77%

**Second Half** (260 trades)
- CAGR: -7.00%
- Max DD: 27.56%
- Win Rate: 49.23%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 512 | -10.73% | 30.40% |
| AUDUSD | 284 | 2.54% | 10.55% |
| EURAUD | 508 | -11.20% | 29.47% |
| EURGBP | 506 | -9.81% | 30.12% |
| EURUSD | 491 | -8.62% | 25.70% |
| GBPAUD | 513 | -11.23% | 31.09% |
| GBPNZD | 514 | -11.03% | 30.87% |
| GBPUSD | 504 | -9.56% | 26.16% |
| NZDUSD | 380 | -9.79% | 27.87% |
| USDCHF | 468 | -24.03% | 50.69% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 52 | $2,140.94 | 57.7% | -96.7% |
| GBPAUD | 7 | $-18.42 | 42.9% | +0.8% |
| EURAUD | 12 | $-24.00 | 50.0% | +1.1% |
| GBPNZD | 6 | $-56.59 | 16.7% | +2.6% |
| AUDNZD | 8 | $-110.62 | 37.5% | +5.0% |
| EURGBP | 14 | $-281.81 | 35.7% | +12.7% |
| NZDUSD | 140 | $-285.48 | 47.9% | +12.9% |
| GBPUSD | 16 | $-327.08 | 37.5% | +14.8% |
| EURUSD | 29 | $-504.31 | 44.8% | +22.8% |
| AUDUSD | 236 | $-2,747.26 | 47.9% | +124.1% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -4.29%
- Median CAGR: -3.77%
- 5th pctl CAGR: -7.34%
- 95th pctl CAGR: -1.96%
- Mean DD: 18.68%
- Worst DD: 26.51%
- Runs ending below start: 17

## Section 15 — Monthly Seasonality [MEDIUM MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 7.90
- Kruskal-Wallis p-value: 0.7224
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 51 | $-713.96 | 0.75 | — |
| 2 | 47 | $-628.85 | 0.75 | — |
| 3 | 36 | $610.19 | 1.39 | — |
| 4 | 60 | $-839.15 | 0.77 | — |
| 5 | 45 | $-161.42 | 0.94 | — |
| 6 | 37 | $64.57 | 1.04 | — |
| 7 | 43 | $-18.78 | 0.99 | — |
| 8 | 46 | $-692.45 | 0.67 | — |
| 9 | 40 | $405.31 | 1.25 | — |
| 10 | 44 | $-923.25 | 0.55 | — |
| 11 | 37 | $78.08 | 1.04 | — |
| 12 | 34 | $605.08 | 1.67 | — |

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 5.96 from global mean -4.26
