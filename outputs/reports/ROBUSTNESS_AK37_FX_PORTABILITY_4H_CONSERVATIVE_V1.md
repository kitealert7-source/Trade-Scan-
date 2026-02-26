# ROBUSTNESS REPORT — AK37_FX_PORTABILITY_4H / CONSERVATIVE_V1

Generated: 2026-02-25 17:20:57

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 9026 |
| Win Rate | 43.6% |
| Avg Win | $36.39 |
| Avg Loss | $28.94 |
| Payoff Ratio | 1.26 |
| Expectancy / Trade | $-0.49 |
| Profit Factor | 0.97 |
| Net Profit | $-4,090.66 |
| Max DD (USD) | $8,263.45 |
| Recovery Factor | -0.50 |

## Section 2 — Tail Contribution

- Top 1 trade: -17.32%
- Top 5 trades: -71.48%
- Top 1% (90): -523.86%
- Top 5% (451): -1480.68%
- Total PnL: $-4,090.66

## Section 3 — Tail Removal

**Removing Top 1% (90 trades)**
- Original CAGR: -2.75%
- New CAGR: -100.00%
- Degradation: 3539.24%
- New Equity: $-15,519.92

**Removing Top 5% (451 trades)**
- Original CAGR: -2.75%
- New CAGR: -100.00%
- Degradation: 3539.24%
- New Equity: $-54,660.35

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.01%
- Median CAGR: -0.01%
- 5th pctl CAGR: -0.01%
- 95th pctl CAGR: -0.01%
- Mean DD: 57.58%
- 95th pctl DD: 71.83%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $6,961.95
- CAGR: -1.90%
- Max DD: 67.18%
- Max Loss Streak: 22

## Section 6 — Rolling 1-Year Window

- Total windows: 218
- Negative windows: 130
- Return < -10%: 79
- DD > 15%: 200
- DD > 20%: 145
- Worst return: -44.25%
- Worst DD: 44.25%
- Mean return: -0.78%
- Mean DD: 24.55%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2007 | 377 | $-2,332.91 | 39.8% | $-6.19 |
| 2008 | 574 | $2,721.96 | 45.8% | $4.74 |
| 2009 | 605 | $-1,399.21 | 39.3% | $-2.31 |
| 2010 | 589 | $-341.26 | 41.3% | $-0.58 |
| 2011 | 618 | $-1,574.85 | 43.9% | $-2.55 |
| 2012 | 471 | $-712.87 | 46.1% | $-1.51 |
| 2013 | 471 | $-742.85 | 42.0% | $-1.58 |
| 2014 | 377 | $-1,464.85 | 39.8% | $-3.89 |
| 2015 | 578 | $1,486.40 | 48.4% | $2.57 |
| 2016 | 530 | $-201.13 | 45.5% | $-0.38 |
| 2017 | 419 | $-759.03 | 41.3% | $-1.81 |
| 2018 | 444 | $-75.76 | 42.3% | $-0.17 |
| 2019 | 338 | $-76.33 | 44.1% | $-0.23 |
| 2020 | 378 | $1,640.34 | 44.2% | $4.34 |
| 2021 | 415 | $-343.82 | 41.7% | $-0.83 |
| 2022 | 546 | $-838.04 | 46.3% | $-1.53 |
| 2023 | 470 | $608.63 | 43.6% | $1.29 |
| 2024 | 380 | $-533.49 | 42.1% | $-1.40 |
| 2025 | 405 | $203.91 | 46.4% | $0.50 |
| 2026 | 41 | $644.50 | 58.5% | $15.72 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2007 | +0 | +0 | -35 | -498 | -760 | -390 | +552 | +108 | -581 | +193 | -642 | -281 |
| 2008 | +429 | -69 | +877 | -102 | -745 | +106 | +387 | +2480 | -783 | -82 | -19 | +242 |
| 2009 | -266 | -375 | +1248 | +241 | -629 | -1217 | -387 | +1049 | -27 | -769 | -563 | +295 |
| 2010 | -1134 | -319 | -549 | -50 | +729 | +467 | -615 | +1447 | -917 | -1128 | +1180 | +548 |
| 2011 | +880 | -752 | -1004 | -1038 | +756 | -1 | -303 | -1100 | +413 | -73 | +74 | +573 |
| 2012 | -559 | -5 | -325 | -453 | +617 | +412 | -157 | -327 | +158 | -229 | -143 | +299 |
| 2013 | -480 | +103 | -791 | -343 | +245 | +96 | -316 | +598 | +75 | -272 | +178 | +164 |
| 2014 | -12 | +158 | -243 | +571 | -259 | -254 | +84 | -97 | -408 | -446 | -208 | -351 |
| 2015 | +699 | -327 | -85 | +535 | +285 | +115 | -160 | +130 | +457 | +497 | -402 | -256 |
| 2016 | +287 | -685 | +589 | +155 | -24 | -908 | -28 | +9 | +165 | -2 | +321 | -81 |
| 2017 | -498 | +245 | -41 | +81 | -179 | -183 | +49 | -306 | -136 | +21 | -91 | +278 |
| 2018 | +791 | +259 | +68 | +168 | -180 | -374 | -397 | -40 | +315 | +142 | -410 | -417 |
| 2019 | -560 | +110 | -61 | -222 | +126 | +140 | -211 | +606 | -198 | +126 | +17 | +52 |
| 2020 | -68 | +77 | +1756 | +50 | +241 | +76 | +106 | -992 | +520 | -111 | +30 | -44 |
| 2021 | -347 | -172 | -4 | +84 | -53 | +201 | +232 | +94 | -0 | -69 | -220 | -89 |
| 2022 | -141 | +468 | -92 | -209 | +486 | +851 | -380 | -562 | -243 | +89 | -907 | -200 |
| 2023 | -681 | +207 | +95 | -459 | +119 | -155 | +362 | +127 | +351 | +54 | +568 | +23 |
| 2024 | +596 | -507 | -373 | -605 | +118 | -256 | +142 | -397 | +66 | +351 | +245 | +86 |
| 2025 | +174 | +44 | -68 | +18 | -412 | +52 | +383 | -122 | -133 | +124 | +277 | -131 |
| 2026 | +724 | -80 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2009-04-15
- Trough: 2015-01-13
- Recovery: ONGOING
- Max DD: 68.88%
- Duration: 6148 days
- Trades open: 3015
- Long/Short: 48.7% / 51.3%
- Top-2 symbol concentration: 37.8%
- Trades closed in plunge: 3015
- Win rate: 41.6%
- Avg PnL: $-2.74
- Max loss streak: 22

### Cluster 2
- Start: 2007-03-29
- Trough: 2007-12-14
- Recovery: 2008-08-19
- Max DD: 23.45%
- Duration: 509 days
- Trades open: 363
- Long/Short: 47.7% / 52.3%
- Top-2 symbol concentration: 40.2%
- Trades closed in plunge: 363
- Win rate: 39.4%
- Avg PnL: $-6.46
- Max loss streak: 11

### Cluster 3
- Start: 2008-10-07
- Trough: 2009-02-11
- Recovery: 2009-03-23
- Max DD: 14.28%
- Duration: 167 days
- Trades open: 217
- Long/Short: 51.6% / 48.4%
- Top-2 symbol concentration: 36.9%
- Trades closed in plunge: 217
- Win rate: 42.4%
- Avg PnL: $-7.42
- Max loss streak: 12

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 20 | 22 |
| Avg Streak | 2.3 | 2.9 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-4,090.66 | 0.97 | 0.00% |
| Slip 1.0 pip RT | $-9,823.46 | 0.93 | -140.14% |
| Spread +50% | $-7,965.00 | 0.95 | -94.71% |
| Severe (1.0 + 75%) | $-15,634.97 | 0.90 | -282.21% |

## Section 10 — Directional Robustness

- Total Longs: 4404
- Total Shorts: 4622
- Baseline PF: 0.97
- No Top-20 Longs PF: 0.93
- No Top-20 Shorts PF: 0.93
- No Both PF: 0.89

## Section 11 — Early/Late Split

**First Half** (4513 trades)
- CAGR: -6.94%
- Max DD: 68.97%
- Win Rate: 42.94%

**Second Half** (4513 trades)
- CAGR: 0.44%
- Max DD: 28.97%
- Win Rate: 44.16%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 7220 | -0.77% | 47.08% |
| EURUSD | 7371 | -0.97% | 49.46% |
| GBPUSD | 7494 | -4.05% | 76.54% |
| NZDUSD | 7581 | -2.14% | 62.83% |
| USDCAD | 7737 | -1.99% | 63.07% |
| USDCHF | 7727 | -4.13% | 74.88% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 1299 | $1,396.35 | 42.6% | -34.1% |
| GBPUSD | 1532 | $1,325.24 | 46.0% | -32.4% |
| NZDUSD | 1445 | $-738.67 | 45.3% | +18.1% |
| USDCAD | 1289 | $-938.13 | 43.2% | +22.9% |
| EURUSD | 1655 | $-2,408.20 | 42.6% | +58.9% |
| AUDUSD | 1806 | $-2,727.25 | 41.8% | +66.7% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -1.04%
- Median CAGR: -0.67%
- 5th pctl CAGR: -8.17%
- 95th pctl CAGR: 5.95%
- Mean DD: 65.45%
- Worst DD: 91.18%
- Runs ending below start: 26
