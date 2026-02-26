# ROBUSTNESS REPORT — AK35_FX_PORTABILITY_4H / AGGRESSIVE_V1

Generated: 2026-02-25 12:05:52

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 812 |
| Win Rate | 45.6% |
| Avg Win | $199.11 |
| Avg Loss | $177.27 |
| Payoff Ratio | 1.12 |
| Expectancy / Trade | $-5.77 |
| Profit Factor | 0.94 |
| Net Profit | $-4,681.48 |
| Max DD (USD) | $7,551.00 |
| Recovery Factor | -0.62 |

## Section 2 — Tail Contribution

- Top 1 trade: -28.03%
- Top 5 trades: -131.91%
- Top 1% (8): -197.24%
- Top 5% (40): -630.75%
- Total PnL: $-4,681.48

## Section 3 — Tail Removal

**Removing Top 1% (8 trades)**
- Original CAGR: -3.29%
- New CAGR: -100.00%
- Degradation: 2937.34%
- New Equity: $-3,915.26

**Removing Top 5% (40 trades)**
- Original CAGR: -3.29%
- New CAGR: -100.00%
- Degradation: 2937.34%
- New Equity: $-24,210.12

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.02%
- Median CAGR: -0.02%
- 5th pctl CAGR: -0.02%
- 95th pctl CAGR: -0.02%
- Mean DD: 71.09%
- 95th pctl DD: 83.79%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $5,887.08
- CAGR: -2.77%
- Max DD: 66.91%
- Max Loss Streak: 10

## Section 6 — Rolling 1-Year Window

- Total windows: 218
- Negative windows: 113
- Return < -10%: 80
- DD > 15%: 162
- DD > 20%: 122
- Worst return: -65.67%
- Worst DD: 67.03%
- Mean return: 3.50%
- Mean DD: 23.65%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2007 | 44 | $-2,711.04 | 36.4% | $-61.61 |
| 2008 | 77 | $3,616.16 | 45.5% | $46.96 |
| 2009 | 59 | $-7,112.82 | 28.8% | $-120.56 |
| 2010 | 51 | $1,010.22 | 49.0% | $19.81 |
| 2011 | 60 | $1,014.10 | 45.0% | $16.90 |
| 2012 | 22 | $-753.55 | 36.4% | $-34.25 |
| 2013 | 44 | $1,091.08 | 56.8% | $24.80 |
| 2014 | 27 | $1,358.76 | 48.1% | $50.32 |
| 2015 | 58 | $2,532.26 | 56.9% | $43.66 |
| 2016 | 47 | $-2,234.05 | 46.8% | $-47.53 |
| 2017 | 26 | $-345.46 | 42.3% | $-13.29 |
| 2018 | 38 | $203.46 | 50.0% | $5.35 |
| 2019 | 19 | $-1,125.02 | 26.3% | $-59.21 |
| 2020 | 43 | $4,508.84 | 62.8% | $104.86 |
| 2021 | 32 | $-330.80 | 50.0% | $-10.34 |
| 2022 | 46 | $-2,220.23 | 34.8% | $-48.27 |
| 2023 | 39 | $1,644.21 | 61.5% | $42.16 |
| 2024 | 41 | $-1,723.08 | 41.5% | $-42.03 |
| 2025 | 34 | $-2,357.28 | 35.3% | $-69.33 |
| 2026 | 5 | $-747.24 | 40.0% | $-149.45 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2007 | +0 | +0 | +0 | -264 | +0 | -1063 | -279 | -846 | -20 | -47 | -191 | +0 |
| 2008 | -474 | -354 | +1744 | -549 | +29 | -62 | -1202 | +584 | +1885 | +474 | +273 | +1267 |
| 2009 | +0 | +210 | -1787 | -639 | -2403 | -644 | +0 | -907 | -685 | -25 | -233 | +0 |
| 2010 | -49 | +310 | +34 | +0 | +681 | +372 | -189 | +571 | -905 | +229 | +102 | -147 |
| 2011 | +219 | -391 | -226 | -240 | +206 | -92 | -171 | +1184 | -196 | +1095 | +2 | -376 |
| 2012 | +0 | +0 | +270 | +42 | -906 | +449 | -165 | -64 | -443 | +193 | -128 | +0 |
| 2013 | -78 | -158 | -367 | -23 | +654 | -66 | +485 | -165 | +78 | +849 | +492 | -610 |
| 2014 | -53 | +168 | +0 | -79 | +168 | -3 | +0 | +415 | +0 | +1194 | +395 | -846 |
| 2015 | -375 | -114 | +359 | +0 | -272 | +524 | -442 | +455 | +786 | -143 | +117 | +1637 |
| 2016 | +1197 | +943 | -1265 | -676 | -218 | -603 | -21 | -1136 | -422 | -270 | +16 | +221 |
| 2017 | -585 | +0 | +83 | -481 | +305 | -432 | +22 | +148 | -334 | +0 | +929 | -0 |
| 2018 | +324 | -148 | +635 | +0 | +1228 | +0 | -521 | +47 | +0 | -25 | -666 | -670 |
| 2019 | -368 | -502 | -23 | +0 | +406 | -332 | -343 | +0 | -129 | +174 | +356 | -364 |
| 2020 | -387 | +693 | +2989 | +717 | -396 | +1247 | +0 | +96 | +0 | -342 | -659 | +551 |
| 2021 | -141 | +179 | +783 | +266 | -1331 | +81 | +0 | -223 | -305 | +0 | +0 | +360 |
| 2022 | -60 | -572 | -1293 | -381 | +299 | +578 | -539 | +0 | +652 | -360 | -1408 | +864 |
| 2023 | -95 | +173 | -315 | -911 | +119 | +832 | +285 | +1285 | -184 | -547 | -245 | +1248 |
| 2024 | +569 | +0 | -55 | -176 | -2062 | -334 | +0 | +227 | -477 | +0 | +1674 | -1090 |
| 2025 | -519 | +27 | -709 | -842 | +158 | +0 | -144 | -165 | -571 | +0 | +231 | +176 |
| 2026 | -779 | +31 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2009-02-11
- Trough: 2010-01-11
- Recovery: 2016-01-27
- Max DD: 67.03%
- Duration: 2541 days
- Trades open: 61
- Long/Short: 47.5% / 52.5%
- Top-2 symbol concentration: 47.5%
- Trades closed in plunge: 58
- Win rate: 25.9%
- Avg PnL: $-131.67
- Max loss streak: 7

### Cluster 2
- Start: 2016-03-07
- Trough: 2026-01-26
- Recovery: ONGOING
- Max DD: 58.82%
- Duration: 3627 days
- Trades open: 356
- Long/Short: 48.3% / 51.7%
- Top-2 symbol concentration: 46.6%
- Trades closed in plunge: 355
- Win rate: 44.8%
- Avg PnL: $-19.08
- Max loss streak: 10

### Cluster 3
- Start: 2007-04-11
- Trough: 2008-07-30
- Recovery: 2008-12-19
- Max DD: 35.78%
- Duration: 618 days
- Trades open: 85
- Long/Short: 47.1% / 52.9%
- Top-2 symbol concentration: 54.1%
- Trades closed in plunge: 83
- Win rate: 39.8%
- Avg PnL: $-37.65
- Max loss streak: 6

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 10 | 10 |
| Avg Streak | 2.0 | 2.3 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-4,681.48 | 0.94 | 0.00% |
| Slip 1.0 pip RT | $-5,901.58 | 0.93 | -26.06% |
| Spread +50% | $-5,495.56 | 0.93 | -17.39% |
| Severe (1.0 + 75%) | $-7,122.69 | 0.91 | -52.15% |

## Section 10 — Directional Robustness

- Total Longs: 397
- Total Shorts: 415
- Baseline PF: 0.94
- No Top-20 Longs PF: 0.77
- No Top-20 Shorts PF: 0.74
- No Both PF: 0.57

## Section 11 — Early/Late Split

**First Half** (406 trades)
- CAGR: -3.56%
- Max DD: 68.27%
- Win Rate: 43.84%

**Second Half** (406 trades)
- CAGR: -2.23%
- Max DD: 49.51%
- Win Rate: 47.29%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 602 | 0.34% | 53.84% |
| EURUSD | 673 | -0.29% | 47.34% |
| GBPUSD | 687 | -6.46% | 76.60% |
| NZDUSD | 667 | -0.76% | 43.99% |
| USDCAD | 724 | -1.84% | 58.43% |
| USDCHF | 707 | -100.00% | 121.63% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 105 | $7,404.86 | 51.4% | -158.2% |
| GBPUSD | 125 | $2,477.33 | 49.6% | -52.9% |
| USDCAD | 88 | $-1,735.50 | 38.6% | +37.1% |
| NZDUSD | 145 | $-3,336.03 | 46.2% | +71.3% |
| EURUSD | 139 | $-4,156.33 | 43.9% | +88.8% |
| AUDUSD | 210 | $-5,335.81 | 43.8% | +114.0% |
