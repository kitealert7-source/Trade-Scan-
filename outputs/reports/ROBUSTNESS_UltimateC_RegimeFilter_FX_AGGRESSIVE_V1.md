# ROBUSTNESS REPORT — UltimateC_RegimeFilter_FX / AGGRESSIVE_V1

Generated: 2026-02-25 18:08:51

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 109 |
| Win Rate | 54.1% |
| Avg Win | $103.42 |
| Avg Loss | $106.58 |
| Payoff Ratio | 0.97 |
| Expectancy / Trade | $7.09 |
| Profit Factor | 1.15 |
| Net Profit | $773.00 |
| Max DD (USD) | $706.18 |
| Recovery Factor | 1.09 |

## Section 2 — Tail Contribution

- Top 1 trade: 39.00%
- Top 5 trades: 173.54%
- Top 1% (1): 39.00%
- Top 5% (5): 173.54%
- Total PnL: $773.00

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 3.61%
- New CAGR: 2.22%
- Degradation: 38.53%
- New Equity: $10,471.56

**Removing Top 5% (5 trades)**
- Original CAGR: 3.61%
- New CAGR: -2.75%
- Degradation: 176.16%
- New Equity: $9,431.50

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.04%
- Median CAGR: 0.04%
- 5th pctl CAGR: 0.04%
- 95th pctl CAGR: 0.04%
- Mean DD: 9.85%
- 95th pctl DD: 14.61%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $10,773.57
- CAGR: 3.61%
- Max DD: 6.34%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 0.29%
- Worst DD: 6.35%
- Mean return: 6.95%
- Mean DD: 5.72%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 25 | $72.60 | 56.0% | $2.90 |
| 2025 | 79 | $957.15 | 55.7% | $12.12 |
| 2026 | 5 | $-256.75 | 20.0% | $-51.35 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -6 | +150 | +0 | +0 | +16 | +0 | +0 | -365 | +200 | -114 | +192 |
| 2025 | -50 | -74 | +950 | -71 | -37 | -331 | +309 | +175 | +85 | +0 | +0 |
| 2026 | -27 | -230 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-04-08
- Trough: 2025-06-18
- Recovery: ONGOING
- Max DD: 6.35%
- Duration: 309 days
- Trades open: 37
- Long/Short: 54.1% / 45.9%
- Top-2 symbol concentration: 97.3%
- Trades closed in plunge: 36
- Win rate: 41.7%
- Avg PnL: $-16.81
- Max loss streak: 5

### Cluster 2
- Start: 2024-11-21
- Trough: 2024-11-26
- Recovery: 2025-03-07
- Max DD: 4.83%
- Duration: 106 days
- Trades open: 5
- Long/Short: 60.0% / 40.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 25.0%
- Avg PnL: $-75.02
- Max loss streak: 2

### Cluster 3
- Start: 2024-01-11
- Trough: 2024-08-07
- Recovery: 2024-11-11
- Max DD: 3.64%
- Duration: 305 days
- Trades open: 5
- Long/Short: 60.0% / 40.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 40.0%
- Avg PnL: $-46.33
- Max loss streak: 2

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 9 | 5 |
| Avg Streak | 2.1 | 1.9 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $773.00 | 1.15 | 0.00% |
| Slip 1.0 pip RT | $372.30 | 1.07 | 51.84% |
| Spread +50% | $557.38 | 1.10 | 27.89% |
| Severe (1.0 + 75%) | $48.86 | 1.01 | 93.68% |

## Section 10 — Directional Robustness

- Total Longs: 60
- Total Shorts: 49
- Baseline PF: 1.15
- No Top-20 Longs PF: 0.57
- No Top-20 Shorts PF: 0.70
- No Both PF: 0.13

## Section 11 — Early/Late Split

**First Half** (54 trades)
- CAGR: 7.55%
- Max DD: 5.60%
- Win Rate: 61.11%

**Second Half** (55 trades)
- CAGR: -1.46%
- Max DD: 6.91%
- Win Rate: 47.27%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| EURAUD | 99 | 5.03% | 7.28% |
| EURUSD | 12 | -3.98% | 5.92% |
| GBPNZD | 107 | 4.87% | 6.09% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| EURUSD | 97 | $1,364.71 | 58.8% | +176.5% |
| GBPNZD | 2 | $-277.57 | 0.0% | -35.9% |
| EURAUD | 10 | $-314.14 | 20.0% | -40.6% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 1.41%
- Median CAGR: 1.45%
- 5th pctl CAGR: -0.90%
- 95th pctl CAGR: 3.62%
- Mean DD: 3.12%
- Worst DD: 3.97%
- Runs ending below start: 67
