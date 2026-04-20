# ROBUSTNESS REPORT — UltimateC_RegimeFilter_FX / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-26 14:53:21

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 650 |
| Win Rate | 47.7% |
| Avg Win | $51.50 |
| Avg Loss | $51.15 |
| Payoff Ratio | 1.01 |
| Expectancy / Trade | $-2.20 |
| Profit Factor | 0.92 |
| Net Profit | $-1,428.04 |
| Max DD (USD) | $2,857.12 |
| Recovery Factor | -0.50 |

## Section 2 — Tail Contribution

- Top 1 trade: -20.65%
- Top 5 trades: -87.94%
- Top 1% (6): -100.56%
- Top 5% (32): -337.33%
- Total PnL: $-1,428.04

## Section 3 — Tail Removal

**Removing Top 1% (6 trades)**
- Original CAGR: -7.04%
- New CAGR: -14.78%
- Degradation: 109.86%
- New Equity: $7,135.91

**Removing Top 5% (32 trades)**
- Original CAGR: -7.04%
- New CAGR: -37.14%
- Degradation: 427.36%
- New Equity: $3,754.71

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.07%
- Median CAGR: -0.07%
- 5th pctl CAGR: -0.07%
- 95th pctl CAGR: -0.07%
- Mean DD: 22.99%
- 95th pctl DD: 29.27%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $8,571.38
- CAGR: -7.04%
- Max DD: 25.99%
- Max Loss Streak: 11

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 13
- Return < -10%: 6
- DD > 15%: 14
- DD > 20%: 6
- Worst return: -13.44%
- Worst DD: 22.04%
- Mean return: -8.91%
- Mean DD: 19.28%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 335 | $-642.30 | 48.7% | $-1.92 |
| 2025 | 282 | $-793.82 | 46.5% | $-2.81 |
| 2026 | 33 | $8.08 | 48.5% | $0.24 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -621 | +1043 | +91 | +297 | +8 | -696 | -360 | -515 | -376 | +176 | +299 | +11 |
| 2025 | +219 | -194 | +306 | +260 | -584 | -536 | -234 | -63 | -223 | -79 | -80 | +415 |
| 2026 | +74 | -66 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-04-29
- Trough: 2025-12-01
- Recovery: ONGOING
- Max DD: 25.98%
- Duration: 654 days
- Trades open: 491
- Long/Short: 53.2% / 46.8%
- Top-2 symbol concentration: 82.7%
- Trades closed in plunge: 490
- Win rate: 44.7%
- Avg PnL: $-5.81
- Max loss streak: 11

### Cluster 2
- Start: 2024-01-10
- Trough: 2024-01-31
- Recovery: 2024-02-14
- Max DD: 6.82%
- Duration: 35 days
- Trades open: 28
- Long/Short: 39.3% / 60.7%
- Top-2 symbol concentration: 78.6%
- Trades closed in plunge: 28
- Win rate: 39.3%
- Avg PnL: $-22.18
- Max loss streak: 3

### Cluster 3
- Start: 2024-03-06
- Trough: 2024-03-14
- Recovery: 2024-03-28
- Max DD: 3.07%
- Duration: 22 days
- Trades open: 7
- Long/Short: 57.1% / 42.9%
- Top-2 symbol concentration: 85.7%
- Trades closed in plunge: 6
- Win rate: 16.7%
- Avg PnL: $-33.07
- Max loss streak: 5

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 9 | 11 |
| Avg Streak | 1.9 | 2.1 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-1,428.04 | 0.92 | 0.00% |
| Slip 1.0 pip RT | $-3,030.64 | 0.83 | -112.22% |
| Spread +50% | $-2,706.74 | 0.85 | -89.54% |
| Severe (1.0 + 75%) | $-4,948.69 | 0.74 | -246.54% |

## Section 10 — Directional Robustness

- Total Longs: 342
- Total Shorts: 308
- Baseline PF: 0.92
- No Top-20 Longs PF: 0.75
- No Top-20 Shorts PF: 0.76
- No Both PF: 0.60

## Section 11 — Early/Late Split

**First Half** (325 trades)
- CAGR: -5.66%
- Max DD: 22.04%
- Win Rate: 48.31%

**Second Half** (325 trades)
- CAGR: -7.79%
- Max DD: 17.91%
- Win Rate: 47.08%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| EURAUD | 462 | -5.32% | 19.51% |
| EURUSD | 307 | -1.83% | 16.81% |
| GBPNZD | 531 | -6.83% | 23.68% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| GBPNZD | 119 | $-41.37 | 48.7% | +2.9% |
| EURAUD | 188 | $-340.41 | 50.0% | +23.8% |
| EURUSD | 343 | $-1,046.26 | 46.1% | +73.3% |

## Section 14 — Block Bootstrap (100 runs)

- [SKIPPED] Block bootstrap failed: No backtest directories found for prefix: UltimateC_RegimeFilter_FX

## Section 15 — Monthly Seasonality [MEDIUM MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 21.97
- Kruskal-Wallis p-value: 0.0246
- Effect size (η²): 0.0172

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 85 | $-327.43 | 0.86 | — |
| 2 | 61 | $783.06 | 1.63 | — |
| 3 | 45 | $397.33 | 1.40 | — |
| 4 | 71 | $556.83 | 1.33 | — |
| 5 | 53 | $-576.45 | 0.65 | — |
| 6 | 50 | $-1,232.45 | 0.39 | — |
| 7 | 42 | $-594.04 | 0.56 | — |
| 8 | 53 | $-577.92 | 0.66 | — |
| 9 | 40 | $-598.79 | 0.51 | — |
| 10 | 60 | $96.93 | 1.07 | — |
| 11 | 45 | $218.74 | 1.25 | — |
| 12 | 45 | $426.15 | 1.45 | — |

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 10.45 from global mean -2.20
