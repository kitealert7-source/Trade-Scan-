# ROBUSTNESS REPORT — AK37_FX_PORTABILITY_4H / AGGRESSIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-26 14:39:31

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 4857 |
| Win Rate | 42.9% |
| Avg Win | $60.23 |
| Avg Loss | $47.45 |
| Payoff Ratio | 1.27 |
| Expectancy / Trade | $-1.23 |
| Profit Factor | 0.96 |
| Net Profit | $-5,773.21 |
| Max DD (USD) | $9,592.73 |
| Recovery Factor | -0.60 |

## Section 2 — Tail Contribution

- Top 1 trade: -24.55%
- Top 5 trades: -77.68%
- Top 1% (48): -352.90%
- Top 5% (242): -961.89%
- Total PnL: $-5,773.21

## Section 3 — Tail Removal

**Removing Top 1% (48 trades)**
- Original CAGR: -4.46%
- New CAGR: -100.00%
- Degradation: 2142.82%
- New Equity: $-16,146.67

**Removing Top 5% (242 trades)**
- Original CAGR: -4.46%
- New CAGR: -100.00%
- Degradation: 2142.82%
- New Equity: $-51,305.36

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.02%
- Median CAGR: -0.02%
- 5th pctl CAGR: -0.03%
- 95th pctl CAGR: -0.02%
- Mean DD: 73.78%
- 95th pctl DD: 85.26%
- Blow-up runs (>90% DD): 5

## Section 5 — Reverse Path Test

- Final Equity: $5,397.90
- CAGR: -3.21%
- Max DD: 79.53%
- Max Loss Streak: 19

## Section 6 — Rolling 1-Year Window

- Total windows: 218
- Negative windows: 122
- Return < -10%: 86
- DD > 15%: 193
- DD > 20%: 173
- Worst return: -54.98%
- Worst DD: 55.04%
- Mean return: -0.67%
- Mean DD: 28.31%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2007 | 206 | $-2,916.83 | 40.3% | $-14.16 |
| 2008 | 352 | $2,129.05 | 44.9% | $6.05 |
| 2009 | 418 | $-2,990.55 | 37.6% | $-7.15 |
| 2010 | 343 | $934.98 | 41.7% | $2.73 |
| 2011 | 361 | $-558.10 | 45.4% | $-1.55 |
| 2012 | 224 | $-901.91 | 44.6% | $-4.03 |
| 2013 | 230 | $-716.74 | 42.2% | $-3.12 |
| 2014 | 183 | $-1,797.40 | 36.1% | $-9.82 |
| 2015 | 312 | $-15.83 | 46.8% | $-0.05 |
| 2016 | 275 | $-37.71 | 44.7% | $-0.14 |
| 2017 | 197 | $-658.06 | 38.6% | $-3.34 |
| 2018 | 210 | $145.77 | 43.3% | $0.69 |
| 2019 | 161 | $346.77 | 46.6% | $2.15 |
| 2020 | 204 | $1,364.22 | 46.1% | $6.69 |
| 2021 | 210 | $645.78 | 43.8% | $3.08 |
| 2022 | 293 | $-1,663.34 | 43.7% | $-5.68 |
| 2023 | 223 | $-187.49 | 40.8% | $-0.84 |
| 2024 | 205 | $-99.15 | 41.5% | $-0.48 |
| 2025 | 229 | $993.24 | 46.3% | $4.34 |
| 2026 | 21 | $210.09 | 47.6% | $10.00 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2007 | +0 | +0 | -75 | -577 | -768 | -525 | +770 | +119 | -741 | +162 | -1085 | -197 |
| 2008 | +41 | -226 | +1199 | +397 | -549 | +111 | +588 | +2286 | -970 | -592 | +80 | -236 |
| 2009 | -338 | -476 | +1748 | +719 | -1409 | -2263 | -353 | +778 | -213 | -893 | -584 | +294 |
| 2010 | -765 | +178 | -78 | -67 | +563 | +823 | -691 | +1440 | -690 | -1323 | +993 | +552 |
| 2011 | +1263 | -690 | -433 | -926 | +615 | -36 | -68 | -1292 | +521 | +2 | +260 | +226 |
| 2012 | -585 | +186 | -336 | -407 | +802 | +397 | -312 | -541 | +27 | -414 | +148 | +135 |
| 2013 | -878 | +82 | -645 | -447 | +234 | -131 | -289 | +592 | +382 | -220 | +346 | +258 |
| 2014 | -113 | +53 | -289 | +404 | -245 | -287 | +34 | -220 | -297 | -182 | -173 | -483 |
| 2015 | +211 | -386 | -195 | +342 | +364 | -198 | -329 | -95 | +257 | +91 | -159 | +82 |
| 2016 | +236 | -469 | +308 | +197 | -48 | -397 | -121 | -135 | +266 | -49 | +160 | +12 |
| 2017 | -243 | +175 | +148 | -114 | -334 | -209 | -16 | -208 | -3 | -7 | -123 | +276 |
| 2018 | +445 | +156 | +241 | +183 | -194 | -211 | -277 | +52 | +126 | +79 | -367 | -88 |
| 2019 | -403 | +53 | -58 | -29 | +128 | +144 | -65 | +312 | -43 | +10 | +259 | +38 |
| 2020 | -58 | +23 | +1499 | +181 | -85 | -40 | +126 | -625 | +415 | -68 | -43 | +39 |
| 2021 | -422 | +145 | +107 | +217 | -124 | +103 | +299 | -119 | +289 | +73 | +157 | -78 |
| 2022 | -168 | +2 | -425 | -7 | +536 | +662 | -423 | -575 | -707 | +236 | -693 | -100 |
| 2023 | -412 | -30 | +150 | -349 | +107 | -191 | +155 | +81 | +60 | -19 | +241 | +19 |
| 2024 | +247 | -220 | -278 | -237 | -6 | -107 | +229 | -145 | +144 | +246 | +38 | -11 |
| 2025 | +165 | +24 | -31 | +556 | -381 | +4 | +314 | -53 | -49 | +137 | +371 | -62 |
| 2026 | +316 | -106 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2009-04-23
- Trough: 2019-04-24
- Recovery: ONGOING
- Max DD: 81.80%
- Duration: 6140 days
- Trades open: 2695
- Long/Short: 47.4% / 52.6%
- Top-2 symbol concentration: 44.2%
- Trades closed in plunge: 2695
- Win rate: 41.9%
- Avg PnL: $-3.56
- Max loss streak: 19

### Cluster 2
- Start: 2007-03-29
- Trough: 2008-02-18
- Recovery: 2008-08-19
- Max DD: 31.23%
- Duration: 509 days
- Trades open: 253
- Long/Short: 51.0% / 49.0%
- Top-2 symbol concentration: 47.0%
- Trades closed in plunge: 253
- Win rate: 40.7%
- Avg PnL: $-12.34
- Max loss streak: 10

### Cluster 3
- Start: 2008-10-07
- Trough: 2009-03-11
- Recovery: 2009-04-07
- Max DD: 28.77%
- Duration: 182 days
- Trades open: 209
- Long/Short: 53.1% / 46.9%
- Top-2 symbol concentration: 39.7%
- Trades closed in plunge: 209
- Win rate: 43.1%
- Avg PnL: $-15.74
- Max loss streak: 10

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 11 | 19 |
| Avg Streak | 2.2 | 2.9 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-5,773.21 | 0.96 | 0.00% |
| Slip 1.0 pip RT | $-10,394.71 | 0.92 | -80.05% |
| Spread +50% | $-8,858.39 | 0.93 | -53.44% |
| Severe (1.0 + 75%) | $-15,022.48 | 0.89 | -160.21% |

## Section 10 — Directional Robustness

- Total Longs: 2332
- Total Shorts: 2525
- Baseline PF: 0.96
- No Top-20 Longs PF: 0.89
- No Top-20 Shorts PF: 0.89
- No Both PF: 0.82

## Section 11 — Early/Late Split

**First Half** (2428 trades)
- CAGR: -13.50%
- Max DD: 76.01%
- Win Rate: 42.01%

**Second Half** (2429 trades)
- CAGR: 0.98%
- Max DD: 25.58%
- Win Rate: 43.85%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 3561 | -0.91% | 50.11% |
| EURUSD | 3980 | -4.31% | 80.30% |
| GBPUSD | 4184 | -5.68% | 87.99% |
| NZDUSD | 4119 | -3.29% | 73.94% |
| USDCAD | 4191 | -1.33% | 63.23% |
| USDCHF | 4250 | -8.25% | 89.85% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 607 | $2,256.32 | 44.5% | -39.1% |
| GBPUSD | 673 | $911.17 | 45.3% | -15.8% |
| EURUSD | 877 | $-129.87 | 43.9% | +2.2% |
| NZDUSD | 738 | $-1,088.65 | 43.5% | +18.9% |
| USDCAD | 666 | $-3,541.47 | 41.3% | +61.3% |
| AUDUSD | 1296 | $-4,180.71 | 40.8% | +72.4% |

## Section 14 — Block Bootstrap (100 runs)

- [SKIPPED] Block bootstrap failed: No backtest directories found for prefix: AK37_FX_PORTABILITY_4H

## Section 15 — Monthly Seasonality [FULL MODE]

**Verdict:** No significant calendar pattern
- Kruskal-Wallis H: 7.72
- Kruskal-Wallis p-value: 0.7381
- Effect size (η²): 0.0000

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 419 | $-1,462.03 | 0.88 | — |
| 2 | 378 | $-1,526.40 | 0.83 | — |
| 3 | 395 | $2,556.95 | 1.26 | — |
| 4 | 380 | $35.30 | 1.00 | — |
| 5 | 415 | $-793.86 | 0.93 | — |
| 6 | 433 | $-2,350.09 | 0.82 | — |
| 7 | 395 | $-428.79 | 0.96 | — |
| 8 | 387 | $1,650.99 | 1.16 | — |
| 9 | 404 | $-1,225.34 | 0.90 | — |
| 10 | 428 | $-2,731.03 | 0.79 | — |
| 11 | 413 | $-173.41 | 0.98 | — |
| 12 | 410 | $674.50 | 1.07 | — |

## Section 16 — Weekday Seasonality [FULL MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 38.59
- Kruskal-Wallis p-value: 0.0000
- Effect size (η²): 0.0071

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 911 | $-362.94 | 0.99 | — |
| 2 | 1017 | $11,467.08 | 1.51 | — |
| 3 | 978 | $-4,535.64 | 0.83 | — |
| 4 | 980 | $-7,189.13 | 0.75 | — |
| 5 | 971 | $-5,152.58 | 0.80 | — |
