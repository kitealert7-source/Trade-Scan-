# ROBUSTNESS REPORT — AK35_FX_PORTABILITY_4H / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-26 14:53:17

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 1463 |
| Win Rate | 44.6% |
| Avg Win | $126.45 |
| Avg Loss | $105.33 |
| Payoff Ratio | 1.20 |
| Expectancy / Trade | $-1.88 |
| Profit Factor | 0.97 |
| Net Profit | $-2,751.06 |
| Max DD (USD) | $7,829.50 |
| Recovery Factor | -0.35 |

## Section 2 — Tail Contribution

- Top 1 trade: -50.34%
- Top 5 trades: -158.36%
- Top 1% (14): -354.19%
- Top 5% (73): -1169.13%
- Total PnL: $-2,751.06

## Section 3 — Tail Removal

**Removing Top 1% (14 trades)**
- Original CAGR: -1.69%
- New CAGR: -100.00%
- Degradation: 5812.20%
- New Equity: $-2,495.17

**Removing Top 5% (73 trades)**
- Original CAGR: -1.69%
- New CAGR: -100.00%
- Degradation: 5812.20%
- New Equity: $-24,914.46

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.00%
- Median CAGR: -0.00%
- 5th pctl CAGR: -0.01%
- 95th pctl CAGR: -0.00%
- Mean DD: 56.84%
- 95th pctl DD: 71.72%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $7,657.53
- CAGR: -1.41%
- Max DD: 56.47%
- Max Loss Streak: 13

## Section 6 — Rolling 1-Year Window

- Total windows: 218
- Negative windows: 107
- Return < -10%: 72
- DD > 15%: 146
- DD > 20%: 90
- Worst return: -48.61%
- Worst DD: 49.61%
- Mean return: 2.46%
- Mean DD: 20.92%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2007 | 69 | $-1,530.04 | 34.8% | $-22.17 |
| 2008 | 114 | $3,076.18 | 49.1% | $26.98 |
| 2009 | 84 | $-5,594.55 | 27.4% | $-66.60 |
| 2010 | 77 | $3,049.24 | 50.6% | $39.60 |
| 2011 | 96 | $1,488.32 | 44.8% | $15.50 |
| 2012 | 47 | $-3,914.81 | 31.9% | $-83.29 |
| 2013 | 81 | $1,857.49 | 59.3% | $22.93 |
| 2014 | 84 | $927.83 | 44.0% | $11.05 |
| 2015 | 95 | $2,561.59 | 53.7% | $26.96 |
| 2016 | 86 | $-2,994.44 | 39.5% | $-34.82 |
| 2017 | 62 | $-552.85 | 48.4% | $-8.92 |
| 2018 | 79 | $10.95 | 45.6% | $0.14 |
| 2019 | 51 | $-1,799.16 | 35.3% | $-35.28 |
| 2020 | 79 | $2,700.65 | 50.6% | $34.19 |
| 2021 | 59 | $-842.25 | 42.4% | $-14.28 |
| 2022 | 96 | $-680.78 | 42.7% | $-7.09 |
| 2023 | 68 | $1,138.21 | 55.9% | $16.74 |
| 2024 | 69 | $788.72 | 46.4% | $11.43 |
| 2025 | 59 | $-2,057.94 | 33.9% | $-34.88 |
| 2026 | 8 | $-383.42 | 37.5% | $-47.93 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2007 | +0 | +0 | +0 | -758 | +0 | +92 | +364 | -812 | -347 | +11 | -80 | +0 |
| 2008 | -308 | -244 | +1058 | -510 | +152 | -94 | -1376 | +1471 | +1402 | +727 | +118 | +682 |
| 2009 | +0 | -131 | -1025 | -565 | -1297 | -590 | +0 | -1016 | -665 | +232 | -537 | +0 |
| 2010 | -18 | +825 | -214 | +0 | +1362 | +738 | -162 | +943 | -956 | +415 | +299 | -184 |
| 2011 | +78 | -533 | -93 | -490 | +685 | -264 | -448 | +1494 | -176 | +1383 | +188 | -335 |
| 2012 | +0 | +0 | +615 | -734 | -2421 | +55 | -672 | +164 | -968 | +38 | -100 | +109 |
| 2013 | -183 | -132 | -158 | +111 | +798 | +197 | +583 | -19 | -359 | +886 | +286 | -151 |
| 2014 | -488 | +398 | -30 | +140 | +635 | -113 | +0 | +666 | -247 | +473 | +422 | -929 |
| 2015 | +827 | +28 | +1391 | +0 | -465 | +620 | -555 | +663 | +689 | +165 | -350 | -453 |
| 2016 | +1194 | +602 | -1619 | -1003 | -120 | -1712 | -9 | -577 | -61 | -368 | +827 | -150 |
| 2017 | -491 | -117 | -243 | +198 | -284 | -135 | -374 | +308 | -718 | +0 | +1126 | +178 |
| 2018 | +761 | -162 | +161 | -75 | +825 | -583 | -394 | +78 | +0 | -202 | -250 | -148 |
| 2019 | -1031 | -511 | -166 | +98 | +370 | -859 | -150 | +0 | +629 | -128 | +178 | -229 |
| 2020 | -439 | +572 | +1858 | +205 | -172 | +989 | -517 | -132 | -74 | -253 | -245 | +909 |
| 2021 | -112 | +201 | +310 | +385 | -966 | +215 | +0 | -752 | -219 | +0 | +0 | +95 |
| 2022 | -313 | -249 | -58 | -420 | +471 | +262 | -12 | -558 | +805 | +205 | -890 | +77 |
| 2023 | -49 | +38 | +106 | -533 | +212 | +569 | -109 | +825 | -173 | -537 | +124 | +667 |
| 2024 | +616 | +0 | -139 | -147 | -126 | -516 | +0 | +52 | -382 | +0 | +1592 | -162 |
| 2025 | -777 | -231 | -412 | -949 | +159 | +416 | -325 | -108 | -549 | +0 | +465 | +253 |
| 2026 | -240 | -144 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2016-03-07
- Trough: 2019-07-22
- Recovery: ONGOING
- Max DD: 56.07%
- Duration: 3627 days
- Trades open: 245
- Long/Short: 48.2% / 51.8%
- Top-2 symbol concentration: 42.4%
- Trades closed in plunge: 242
- Win rate: 38.8%
- Avg PnL: $-32.34
- Max loss streak: 13

### Cluster 2
- Start: 2009-02-11
- Trough: 2013-03-04
- Recovery: 2015-03-19
- Max DD: 49.96%
- Duration: 2227 days
- Trades open: 325
- Long/Short: 50.2% / 49.8%
- Top-2 symbol concentration: 39.1%
- Trades closed in plunge: 322
- Win rate: 39.8%
- Avg PnL: $-16.93
- Max loss streak: 9

### Cluster 3
- Start: 2007-04-11
- Trough: 2008-07-30
- Recovery: 2008-09-30
- Max DD: 28.53%
- Duration: 538 days
- Trades open: 135
- Long/Short: 47.4% / 52.6%
- Top-2 symbol concentration: 43.7%
- Trades closed in plunge: 130
- Win rate: 39.2%
- Avg PnL: $-18.21
- Max loss streak: 11

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 11 | 13 |
| Avg Streak | 2.1 | 2.6 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-2,751.06 | 0.97 | 0.00% |
| Slip 1.0 pip RT | $-4,033.56 | 0.95 | -46.62% |
| Spread +50% | $-3,610.44 | 0.96 | -31.24% |
| Severe (1.0 + 75%) | $-5,322.63 | 0.94 | -93.48% |

## Section 10 — Directional Robustness

- Total Longs: 722
- Total Shorts: 741
- Baseline PF: 0.97
- No Top-20 Longs PF: 0.86
- No Top-20 Shorts PF: 0.83
- No Both PF: 0.72

## Section 11 — Early/Late Split

**First Half** (731 trades)
- CAGR: 2.86%
- Max DD: 50.77%
- Win Rate: 45.14%

**Second Half** (732 trades)
- CAGR: -7.39%
- Max DD: 70.15%
- Win Rate: 44.13%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 1156 | 0.21% | 41.07% |
| EURUSD | 1177 | -0.15% | 43.46% |
| GBPUSD | 1215 | -1.57% | 54.62% |
| NZDUSD | 1231 | -0.47% | 46.00% |
| USDCAD | 1280 | -1.69% | 54.13% |
| USDCHF | 1256 | -7.49% | 92.61% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 207 | $4,945.77 | 44.0% | -179.8% |
| USDCAD | 183 | $-4.20 | 43.7% | +0.2% |
| GBPUSD | 248 | $-164.21 | 48.0% | +6.0% |
| NZDUSD | 232 | $-1,896.21 | 44.8% | +68.9% |
| EURUSD | 286 | $-2,469.84 | 42.7% | +89.8% |
| AUDUSD | 307 | $-3,162.37 | 44.6% | +115.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 3.28%
- Median CAGR: 3.27%
- 5th pctl CAGR: -1.16%
- 95th pctl CAGR: 7.62%
- Mean DD: 20.27%
- Worst DD: 60.02%
- Runs ending below start: 67

## Section 15 — Monthly Seasonality [FULL MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 27.40
- Kruskal-Wallis p-value: 0.0040
- Effect size (η²): 0.0113

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 124 | $-973.31 | 0.88 | — |
| 2 | 102 | $208.48 | 1.05 | — |
| 3 | 127 | $1,341.88 | 1.17 | — |
| 4 | 105 | $-5,047.08 | 0.37 | — |
| 5 | 121 | $-183.21 | 0.98 | — |
| 6 | 155 | $-712.49 | 0.92 | — |
| 7 | 92 | $-4,154.67 | 0.40 | — |
| 8 | 146 | $2,690.26 | 1.41 | — |
| 9 | 112 | $-2,370.64 | 0.67 | — |
| 10 | 124 | $3,046.41 | 1.55 | — |
| 11 | 143 | $3,172.41 | 1.45 | — |
| 12 | 112 | $230.90 | 1.04 | — |

## Section 16 — Weekday Seasonality [FULL MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 11.94
- Kruskal-Wallis p-value: 0.0178
- Effect size (η²): 0.0054

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 348 | $-8,219.00 | 0.65 | — |
| 2 | 204 | $3,269.05 | 1.34 | — |
| 3 | 282 | $3,139.44 | 1.20 | — |
| 4 | 329 | $-7,168.94 | 0.70 | — |
| 5 | 299 | $6,344.49 | 1.49 | — |
