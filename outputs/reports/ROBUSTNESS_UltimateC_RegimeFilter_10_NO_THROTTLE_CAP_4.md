# ROBUSTNESS REPORT — UltimateC_RegimeFilter_10 / NO_THROTTLE_CAP_4

Engine: Robustness v2.1.1 | Generated: 2026-03-03 14:42:53

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2762 |
| Win Rate | 55.2% |
| Avg Win | $46.55 |
| Avg Loss | $52.62 |
| Payoff Ratio | 0.88 |
| Expectancy / Trade | $2.14 |
| Profit Factor | 1.10 |
| Net Profit | $6,222.41 |
| Max DD (USD) | $2,831.40 |
| Recovery Factor | 2.20 |

## Section 2 — Tail Contribution

- Top 1 trade: 7.61%
- Top 5 trades: 30.15%
- Top 1% (27): 103.98%
- Top 5% (138): 339.42%
- Total PnL: $6,222.41

## Section 3 — Tail Removal

**Removing Top 1% (27 trades)**
- Original CAGR: 43.10%
- New CAGR: -1.84%
- Degradation: 104.27%
- New Equity: $9,752.47

**Removing Top 5% (138 trades)**
- Original CAGR: 43.10%
- New CAGR: -100.00%
- Degradation: 332.02%
- New Equity: $-4,897.67

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.44%
- Median CAGR: 0.44%
- 5th pctl CAGR: 0.44%
- 95th pctl CAGR: 0.45%
- Mean DD: 16.57%
- 95th pctl DD: 24.33%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $16,327.52
- CAGR: 43.69%
- Max DD: 19.55%
- Max Loss Streak: 15

## Section 6 — Rolling 1-Year Window

- Total windows: 5
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 4
- DD > 20%: 0
- Worst return: 17.71%
- Worst DD: 17.69%
- Mean return: 26.66%
- Mean DD: 16.66%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 538 | $2,505.56 | 55.0% | $4.66 |
| 2025 | 1991 | $3,856.64 | 55.7% | $1.94 |
| 2026 | 233 | $-139.79 | 51.9% | $-0.60 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +400 | +1340 | +766 |
| 2025 | +769 | -659 | +168 | +759 | -343 | +1431 | +27 | +150 | -87 | -815 | +595 | +1862 |
| 2026 | -240 | +100 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2025-08-07
- Trough: 2025-10-22
- Recovery: 2025-12-18
- Max DD: 17.69%
- Duration: 133 days
- Trades open: 384
- Long/Short: 52.6% / 47.4%
- Top-2 symbol concentration: 35.7%
- Trades closed in plunge: 382
- Win rate: 54.7%
- Avg PnL: $-6.41
- Max loss streak: 8

### Cluster 2
- Start: 2025-02-14
- Trough: 2025-03-07
- Recovery: 2025-05-07
- Max DD: 11.92%
- Duration: 82 days
- Trades open: 154
- Long/Short: 49.4% / 50.6%
- Top-2 symbol concentration: 39.0%
- Trades closed in plunge: 152
- Win rate: 42.8%
- Avg PnL: $-8.19
- Max loss streak: 15

### Cluster 3
- Start: 2024-10-21
- Trough: 2024-10-31
- Recovery: 2024-11-07
- Max DD: 7.17%
- Duration: 17 days
- Trades open: 78
- Long/Short: 47.4% / 52.6%
- Top-2 symbol concentration: 44.9%
- Trades closed in plunge: 77
- Win rate: 44.2%
- Avg PnL: $-10.21
- Max loss streak: 8

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 16 | 15 |
| Avg Streak | 2.5 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $6,222.41 | 1.10 | 0.00% |
| Slip 1.0 pip RT | $-6,174.99 | 0.91 | 199.24% |
| Spread +50% | $-5,161.60 | 0.93 | 182.95% |
| Severe (1.0 + 75%) | $-23,251.00 | 0.71 | 473.67% |

## Section 10 — Directional Robustness

- Total Longs: 1450
- Total Shorts: 1312
- Baseline PF: 1.10
- No Top-20 Longs PF: 1.02
- No Top-20 Shorts PF: 1.04
- No Both PF: 0.96

## Section 11 — Early/Late Split

**First Half** (1381 trades)
- CAGR: 60.98%
- Max DD: 12.36%
- Win Rate: 54.89%

**Second Half** (1381 trades)
- CAGR: 39.95%
- Max DD: 24.93%
- Win Rate: 55.54%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDNZD | 2367 | 26.83% | 22.58% |
| AUDUSD | 2346 | 33.66% | 21.41% |
| EURUSD | 2369 | 39.05% | 15.26% |
| GBPNZD | 2409 | 33.99% | 21.44% |
| GBPUSD | 2335 | 40.36% | 16.18% |
| USDCHF | 2370 | 40.88% | 19.39% |
| USDJPY | 2376 | 45.13% | 13.61% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| AUDNZD | 395 | $2,430.61 | 61.0% | +39.1% |
| AUDUSD | 416 | $1,416.66 | 54.1% | +22.8% |
| GBPNZD | 353 | $1,367.29 | 57.5% | +22.0% |
| EURUSD | 393 | $603.84 | 52.7% | +9.7% |
| GBPUSD | 427 | $405.21 | 52.9% | +6.5% |
| USDCHF | 392 | $325.38 | 55.4% | +5.2% |
| USDJPY | 386 | $-326.58 | 53.4% | -5.2% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 4.59%
- Median CAGR: 3.23%
- 5th pctl CAGR: -2.07%
- 95th pctl CAGR: 16.45%
- Mean DD: 10.04%
- Worst DD: 16.58%
- Runs ending below start: 85

## Section 15 — Monthly Seasonality [SHORT MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 8.18
- Kruskal-Wallis p-value: 0.6968
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 337 | $529.06 | 1.06 | — |
| 2 | 250 | $-558.50 | 0.90 | — |
| 3 | 191 | $167.75 | 1.04 | — |
| 4 | 192 | $759.47 | 1.18 | — |
| 5 | 140 | $-343.36 | 0.90 | — |
| 6 | 150 | $1,430.53 | 1.56 | — |
| 7 | 206 | $26.70 | 1.01 | — |
| 8 | 136 | $149.81 | 1.03 | — |
| 9 | 154 | $-86.55 | 0.98 | — |
| 10 | 377 | $-415.37 | 0.96 | — |
| 11 | 326 | $1,935.49 | 1.29 | — |
| 12 | 303 | $2,627.38 | 1.40 | — |

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 4.35 from global mean 2.25
