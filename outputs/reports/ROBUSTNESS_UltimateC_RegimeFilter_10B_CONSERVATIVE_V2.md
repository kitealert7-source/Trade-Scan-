# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10B / CONSERVATIVE_V2

Engine: Robustness v2.1.1 | Generated: 2026-03-03 15:44:32

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 5821 |
| Win Rate | 55.1% |
| Avg Win | $48.50 |
| Avg Loss | $55.57 |
| Payoff Ratio | 0.87 |
| Expectancy / Trade | $1.80 |
| Profit Factor | 1.08 |
| Net Profit | $11,656.03 |
| Max DD (USD) | $4,374.53 |
| Recovery Factor | 2.66 |

## Section 2 — Tail Contribution

- Top 1 trade: 6.51%
- Top 5 trades: 26.03%
- Top 1% (58): 142.04%
- Top 5% (291): 433.93%
- Total PnL: $11,656.03

## Section 3 — Tail Removal

**Removing Top 1% (58 trades)**
- Original CAGR: 43.98%
- New CAGR: -27.21%
- Degradation: 161.87%
- New Equity: $5,100.18

**Removing Top 5% (291 trades)**
- Original CAGR: 43.98%
- New CAGR: -100.00%
- Degradation: 327.39%
- New Equity: $-28,923.42

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.47%
- Median CAGR: 0.47%
- 5th pctl CAGR: 0.46%
- 95th pctl CAGR: 0.47%
- Mean DD: 22.72%
- 95th pctl DD: 31.40%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $22,098.85
- CAGR: 45.52%
- Max DD: 31.00%
- Max Loss Streak: 15

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 11
- DD > 20%: 6
- Worst return: 21.88%
- Worst DD: 31.24%
- Mean return: 51.01%
- Mean DD: 21.63%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 3490 | $5,714.52 | 54.9% | $1.64 |
| 2025 | 2097 | $6,089.32 | 55.9% | $2.90 |
| 2026 | 234 | $-147.81 | 52.1% | $-0.63 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -531 | +803 | +1151 | -653 | +2998 | -2190 | -1068 | -395 | +2609 | +158 | +1845 | +985 |
| 2025 | +651 | -872 | +778 | +1417 | -906 | +2219 | -57 | +286 | -217 | -517 | +743 | +2564 |
| 2026 | -288 | +140 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-05-29
- Trough: 2024-09-05
- Recovery: 2024-11-07
- Max DD: 31.24%
- Duration: 162 days
- Trades open: 1055
- Long/Short: 51.8% / 48.2%
- Top-2 symbol concentration: 31.0%
- Trades closed in plunge: 1054
- Win rate: 53.0%
- Avg PnL: $-3.99
- Max loss streak: 7

### Cluster 2
- Start: 2025-08-07
- Trough: 2025-10-22
- Recovery: 2025-12-15
- Max DD: 15.48%
- Duration: 130 days
- Trades open: 404
- Long/Short: 52.7% / 47.3%
- Top-2 symbol concentration: 34.4%
- Trades closed in plunge: 402
- Win rate: 56.0%
- Avg PnL: $-6.78
- Max loss streak: 8

### Cluster 3
- Start: 2024-04-09
- Trough: 2024-04-30
- Recovery: 2024-05-10
- Max DD: 13.40%
- Duration: 31 days
- Trades open: 224
- Long/Short: 53.1% / 46.9%
- Top-2 symbol concentration: 34.4%
- Trades closed in plunge: 224
- Win rate: 47.3%
- Avg PnL: $-6.07
- Max loss streak: 13

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 16 | 15 |
| Avg Streak | 2.5 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $11,656.03 | 1.08 | 0.00% |
| Slip 1.0 pip RT | $-17,096.87 | 0.89 | 246.68% |
| Spread +50% | $-14,311.21 | 0.91 | 222.78% |
| Severe (1.0 + 75%) | $-56,047.73 | 0.69 | 580.85% |

## Section 10 — Directional Robustness

- Total Longs: 3029
- Total Shorts: 2792
- Baseline PF: 1.08
- No Top-20 Longs PF: 1.03
- No Top-20 Shorts PF: 1.04
- No Both PF: 0.99

## Section 11 — Early/Late Split

**First Half** (2910 trades)
- CAGR: 35.82%
- Max DD: 31.34%
- Win Rate: 54.88%

**Second Half** (2911 trades)
- CAGR: 60.67%
- Max DD: 19.75%
- Win Rate: 55.38%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 5026 | 26.02% | 37.98% |
| AUDUSD | 4951 | 38.95% | 25.01% |
| EURUSD | 4992 | 47.08% | 20.18% |
| GBPNZD | 5050 | 33.39% | 35.21% |
| GBPUSD | 4947 | 42.53% | 29.46% |
| USDCHF | 4993 | 42.15% | 29.97% |
| USDJPY | 4967 | 40.20% | 28.45% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDNZD | 795 | $5,353.11 | 60.3% | +45.9% |
| GBPNZD | 771 | $3,271.38 | 56.4% | +28.1% |
| AUDUSD | 870 | $1,614.14 | 53.3% | +13.8% |
| USDJPY | 854 | $1,229.95 | 54.4% | +10.6% |
| USDCHF | 828 | $625.19 | 55.2% | +5.4% |
| GBPUSD | 874 | $507.63 | 53.4% | +4.4% |
| EURUSD | 829 | $-945.37 | 53.3% | -8.1% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 4.47%
- Median CAGR: 4.06%
- 5th pctl CAGR: -2.58%
- 95th pctl CAGR: 15.37%
- Mean DD: 13.71%
- Worst DD: 19.26%
- Runs ending below start: 72

## Section 15 — Monthly Seasonality [MEDIUM MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 13.87
- Kruskal-Wallis p-value: 0.2404
- Effect size (η²): 0.0005

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 643 | $-168.02 | 0.99 | — |
| 2 | 578 | $71.80 | 1.01 | — |
| 3 | 523 | $1,929.24 | 1.19 | — |
| 4 | 544 | $764.37 | 1.06 | — |
| 5 | 468 | $2,092.01 | 1.18 | — |
| 6 | 454 | $29.69 | 1.00 | — |
| 7 | 539 | $-1,124.85 | 0.92 | — |
| 8 | 488 | $-108.44 | 0.99 | — |
| 9 | 468 | $2,391.77 | 1.23 | — |
| 10 | 464 | $-359.25 | 0.97 | — |
| 11 | 344 | $2,588.10 | 1.29 | — |
| 12 | 308 | $3,549.61 | 1.42 | — |

## Section 16 — Weekday Seasonality [MEDIUM MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 2.27
- Kruskal-Wallis p-value: 0.6856
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 1096 | $2,414.64 | 1.09 | — |
| 2 | 1208 | $-15.46 | 1.00 | — |
| 3 | 1216 | $2,688.38 | 1.09 | — |
| 4 | 1128 | $1,929.56 | 1.07 | — |
| 5 | 1169 | $4,885.29 | 1.18 | — |
