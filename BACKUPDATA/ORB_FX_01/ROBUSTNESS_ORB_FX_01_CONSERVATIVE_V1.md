# ROBUSTNESS REPORT — ORB_FX_01 / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-26 19:42:39

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 864 |
| Win Rate | 47.5% |
| Avg Win | $65.68 |
| Avg Loss | $60.82 |
| Payoff Ratio | 1.08 |
| Expectancy / Trade | $-0.79 |
| Profit Factor | 0.98 |
| Net Profit | $-624.53 |
| Max DD (USD) | $4,877.01 |
| Recovery Factor | -0.13 |

## Section 2 — Tail Contribution

- Top 1 trade: -90.13%
- Top 5 trades: -307.13%
- Top 1% (8): -461.15%
- Top 5% (43): -1568.23%
- Total PnL: $-624.53

## Section 3 — Tail Removal

**Removing Top 1% (8 trades)**
- Original CAGR: -3.05%
- New CAGR: -18.73%
- Degradation: 513.66%
- New Equity: $6,495.47

**Removing Top 5% (43 trades)**
- Original CAGR: -3.05%
- New CAGR: -100.00%
- Degradation: 3175.65%
- New Equity: $-418.62

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.03%
- Median CAGR: -0.03%
- 5th pctl CAGR: -0.03%
- 95th pctl CAGR: -0.03%
- Mean DD: 26.94%
- 95th pctl DD: 36.44%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $9,354.41
- CAGR: -3.16%
- Max DD: 36.52%
- Max Loss Streak: 10

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 11
- Return < -10%: 10
- DD > 15%: 14
- DD > 20%: 14
- Worst return: -27.32%
- Worst DD: 36.43%
- Mean return: -13.22%
- Mean DD: 30.28%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 384 | $1,073.34 | 49.2% | $2.80 |
| 2025 | 430 | $-2,158.93 | 46.5% | $-5.02 |
| 2026 | 50 | $461.06 | 42.0% | $9.22 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -194 | +137 | +667 | +118 | +319 | -293 | +89 | +444 | +210 | +228 | +730 | -1381 |
| 2025 | -513 | -282 | +39 | -1474 | +100 | -135 | +750 | -586 | +368 | -364 | -150 | +89 |
| 2026 | +137 | +324 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-11-26
- Trough: 2025-06-13
- Recovery: ONGOING
- Max DD: 36.43%
- Duration: 444 days
- Trades open: 255
- Long/Short: 49.8% / 50.2%
- Top-2 symbol concentration: 41.6%
- Trades closed in plunge: 255
- Win rate: 39.2%
- Avg PnL: $-18.46
- Max loss streak: 10

### Cluster 2
- Start: 2024-01-25
- Trough: 2024-02-06
- Recovery: 2024-03-21
- Max DD: 8.75%
- Duration: 56 days
- Trades open: 12
- Long/Short: 41.7% / 58.3%
- Top-2 symbol concentration: 66.7%
- Trades closed in plunge: 12
- Win rate: 16.7%
- Avg PnL: $-72.20
- Max loss streak: 7

### Cluster 3
- Start: 2024-05-30
- Trough: 2024-07-03
- Recovery: 2024-09-02
- Max DD: 7.68%
- Duration: 95 days
- Trades open: 35
- Long/Short: 48.6% / 51.4%
- Top-2 symbol concentration: 68.6%
- Trades closed in plunge: 35
- Win rate: 42.9%
- Avg PnL: $-17.84
- Max loss streak: 4

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 11 | 10 |
| Avg Streak | 2.1 | 2.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-624.53 | 0.98 | 0.00% |
| Slip 1.0 pip RT | $-3,164.93 | 0.89 | -406.77% |
| Spread +50% | $-2,562.70 | 0.91 | -310.34% |
| Severe (1.0 + 75%) | $-6,072.19 | 0.80 | -872.28% |

## Section 10 — Directional Robustness

- Total Longs: 418
- Total Shorts: 446
- Baseline PF: 0.98
- No Top-20 Longs PF: 0.81
- No Top-20 Shorts PF: 0.81
- No Both PF: 0.64

## Section 11 — Early/Late Split

**First Half** (432 trades)
- CAGR: 4.68%
- Max DD: 25.24%
- Win Rate: 47.92%

**Second Half** (432 trades)
- CAGR: -11.35%
- Max DD: 21.19%
- Win Rate: 46.99%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 819 | -1.98% | 35.53% |
| AUDUSD | 605 | -5.85% | 30.69% |
| EURAUD | 781 | 1.04% | 31.29% |
| EURGBP | 818 | -3.17% | 34.03% |
| EURUSD | 784 | -1.32% | 34.23% |
| GBPAUD | 829 | -2.17% | 34.25% |
| GBPNZD | 818 | -3.20% | 36.60% |
| GBPUSD | 812 | -3.18% | 36.96% |
| NZDUSD | 725 | -0.70% | 30.19% |
| USDCAD | 859 | -2.18% | 35.25% |
| USDCHF | 790 | -8.10% | 39.01% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 74 | $987.68 | 44.6% | -158.1% |
| AUDUSD | 259 | $554.34 | 51.7% | -88.8% |
| GBPNZD | 46 | $29.94 | 45.7% | -4.8% |
| GBPUSD | 52 | $26.78 | 36.5% | -4.3% |
| EURGBP | 46 | $24.41 | 50.0% | -3.9% |
| USDCAD | 5 | $-177.12 | 20.0% | +28.4% |
| GBPAUD | 35 | $-178.35 | 54.3% | +28.6% |
| AUDNZD | 45 | $-217.00 | 42.2% | +34.7% |
| EURUSD | 80 | $-352.50 | 41.2% | +56.4% |
| NZDUSD | 139 | $-479.68 | 49.6% | +76.8% |
| EURAUD | 83 | $-843.03 | 47.0% | +135.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -0.62%
- Median CAGR: -1.91%
- 5th pctl CAGR: -12.99%
- 95th pctl CAGR: 13.78%
- Mean DD: 28.67%
- Worst DD: 51.70%
- Runs ending below start: 42

## Section 15 — Monthly Seasonality [MEDIUM MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 19.33
- Kruskal-Wallis p-value: 0.0554
- Effect size (η²): 0.0098

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 85 | $-569.56 | 0.82 | — |
| 2 | 77 | $179.40 | 1.07 | — |
| 3 | 60 | $705.88 | 1.40 | — |
| 4 | 90 | $-1,355.96 | 0.60 | — |
| 5 | 81 | $418.27 | 1.22 | — |
| 6 | 70 | $-428.81 | 0.81 | — |
| 7 | 69 | $838.86 | 1.56 | — |
| 8 | 71 | $-141.96 | 0.94 | — |
| 9 | 65 | $577.50 | 1.35 | — |
| 10 | 73 | $-136.01 | 0.94 | — |
| 11 | 63 | $580.00 | 1.30 | — |
| 12 | 60 | $-1,292.14 | 0.51 | — |

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 10.72 from global mean -0.72
