# ROBUSTNESS REPORT — SPX02_MR / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-28 10:25:27

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 164 |
| Win Rate | 65.2% |
| Avg Win | $40.74 |
| Avg Loss | $62.41 |
| Payoff Ratio | 0.65 |
| Expectancy / Trade | $4.89 |
| Profit Factor | 1.23 |
| Net Profit | $801.38 |
| Max DD (USD) | $1,125.91 |
| Recovery Factor | 0.71 |

## Section 2 — Tail Contribution

- Top 1 trade: 17.47%
- Top 5 trades: 65.58%
- Top 1% (1): 17.47%
- Top 5% (8): 96.34%
- Total PnL: $801.38

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 0.77%
- New CAGR: 0.64%
- Degradation: 16.98%
- New Equity: $10,661.34

**Removing Top 5% (8 trades)**
- Original CAGR: 0.77%
- New CAGR: 0.03%
- Degradation: 96.22%
- New Equity: $10,029.32

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.01%
- Median CAGR: 0.01%
- 5th pctl CAGR: 0.01%
- 95th pctl CAGR: 0.01%
- Mean DD: 6.81%
- 95th pctl DD: 10.14%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $10,801.38
- CAGR: 0.77%
- Max DD: 10.50%
- Max Loss Streak: 4

## Section 6 — Rolling 1-Year Window

- Total windows: 111
- Negative windows: 46
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -6.72%
- Worst DD: 6.72%
- Mean return: 0.52%
- Mean DD: 2.49%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2016 | 12 | $188.80 | 66.7% | $15.73 |
| 2017 | 12 | $531.47 | 75.0% | $44.29 |
| 2018 | 21 | $-720.89 | 52.4% | $-34.33 |
| 2019 | 14 | $118.05 | 64.3% | $8.43 |
| 2020 | 16 | $-395.94 | 68.8% | $-24.75 |
| 2021 | 14 | $437.02 | 78.6% | $31.22 |
| 2022 | 26 | $-313.10 | 53.8% | $-12.04 |
| 2023 | 16 | $100.74 | 56.2% | $6.30 |
| 2024 | 15 | $480.07 | 80.0% | $32.00 |
| 2025 | 16 | $245.04 | 68.8% | $15.31 |
| 2026 | 2 | $130.12 | 100.0% | $65.06 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | -19 | +8 | +0 | +0 | -1 | +57 | +0 | +0 | +76 | +21 | +47 | +0 |
| 2017 | +84 | +37 | -4 | -14 | +96 | +0 | +88 | +102 | +0 | +0 | +78 | +64 |
| 2018 | +0 | -322 | -82 | -52 | +0 | +70 | +0 | +101 | +18 | -267 | +17 | -203 |
| 2019 | +0 | +0 | +49 | +0 | -125 | +39 | +100 | -56 | +0 | +54 | +0 | +56 |
| 2020 | +4 | -326 | -166 | +0 | +0 | +51 | +49 | +0 | -24 | -60 | +77 | +0 |
| 2021 | +0 | +6 | +28 | +0 | +13 | +108 | +47 | +82 | +20 | -32 | +41 | +123 |
| 2022 | -24 | -43 | +5 | +5 | -35 | -45 | +22 | -51 | -83 | +22 | +10 | -94 |
| 2023 | +59 | -60 | +38 | +66 | +24 | +7 | +0 | -50 | -67 | +32 | +51 | +0 |
| 2024 | +36 | +108 | +0 | +16 | +0 | +26 | -2 | +0 | +22 | +0 | +176 | +97 |
| 2025 | +82 | -87 | -147 | -10 | +32 | +83 | +0 | +128 | +0 | +125 | -4 | +43 |
| 2026 | +130 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2018-02-05
- Trough: 2020-03-19
- Recovery: 2026-01-06
- Max DD: 10.50%
- Duration: 2892 days
- Trades open: 41
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 41
- Win rate: 56.1%
- Avg PnL: $-27.46
- Max loss streak: 3

### Cluster 2
- Start: 2016-01-15
- Trough: 2016-05-04
- Recovery: 2016-05-10
- Max DD: 0.56%
- Duration: 116 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 50.0%
- Avg PnL: $-14.07
- Max loss streak: 1

### Cluster 3
- Start: 2016-05-19
- Trough: 2016-06-17
- Recovery: 2016-06-30
- Max DD: 0.31%
- Duration: 42 days
- Trades open: 2
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 0.0%
- Avg PnL: $-15.72
- Max loss streak: 2

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 4 |
| Avg Streak | 2.8 | 1.5 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $801.38 | 1.23 | 0.00% |
| Slip 1.0 pip RT | $662.18 | 1.18 | 17.37% |
| Spread +50% | $696.98 | 1.19 | 13.03% |
| Severe (1.0 + 75%) | $505.58 | 1.14 | 36.91% |

## Section 10 — Directional Robustness

- Total Longs: 164
- Total Shorts: 0
- Baseline PF: 1.23
- No Top-20 Longs PF: 0.77
- No Top-20 Shorts PF: 1.23
- No Both PF: 0.77

## Section 11 — Early/Late Split

**First Half** (82 trades)
- CAGR: 0.01%
- Max DD: 10.50%
- Win Rate: 65.85%

**Second Half** (82 trades)
- CAGR: 1.76%
- Max DD: 3.14%
- Win Rate: 64.63%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| SPX500 | 164 | $801.38 | 65.2% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 0.62%
- Median CAGR: 0.63%
- 5th pctl CAGR: -2.01%
- 95th pctl CAGR: 2.29%
- Mean DD: 10.28%
- Worst DD: 29.16%
- Runs ending below start: 32

## Section 15 — Monthly Seasonality [FULL MODE]

- SUPPRESSED: 164 trades < 300 threshold
- Dispersion: max deviation 53.38 from global mean 4.89

## Section 16 — Weekday Seasonality [FULL MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 17.17 from global mean 4.89
