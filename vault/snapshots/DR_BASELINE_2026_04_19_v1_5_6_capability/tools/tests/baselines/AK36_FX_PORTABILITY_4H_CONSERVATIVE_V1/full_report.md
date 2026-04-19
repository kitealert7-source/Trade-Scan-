# ROBUSTNESS REPORT — AK36_FX_PORTABILITY_4H / CONSERVATIVE_V1

Engine: Robustness v2.1.1 | Generated: 2026-02-26 14:52:06

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 6532 |
| Win Rate | 49.6% |
| Avg Win | $75.86 |
| Avg Loss | $72.82 |
| Payoff Ratio | 1.04 |
| Expectancy / Trade | $0.95 |
| Profit Factor | 1.03 |
| Net Profit | $6,947.94 |
| Max DD (USD) | $7,886.01 |
| Recovery Factor | 0.88 |

## Section 2 — Tail Contribution

- Top 1 trade: 17.61%
- Top 5 trades: 65.49%
- Top 1% (65): 491.70%
- Top 5% (326): 1441.44%
- Total PnL: $6,947.94

## Section 3 — Tail Removal

**Removing Top 1% (65 trades)**
- Original CAGR: 2.83%
- New CAGR: -100.00%
- Degradation: 3628.96%
- New Equity: $-17,215.30

**Removing Top 5% (326 trades)**
- Original CAGR: 2.83%
- New CAGR: -100.00%
- Degradation: 3628.96%
- New Equity: $-83,202.29

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: 0.04%
- Median CAGR: 0.04%
- 5th pctl CAGR: 0.04%
- 95th pctl CAGR: 0.04%
- Mean DD: 45.10%
- 95th pctl DD: 60.59%
- Blow-up runs (>90% DD): 0

## Section 5 — Reverse Path Test

- Final Equity: $18,929.34
- CAGR: 3.44%
- Max DD: 43.62%
- Max Loss Streak: 13

## Section 6 — Rolling 1-Year Window

- Total windows: 218
- Negative windows: 104
- Return < -10%: 50
- DD > 15%: 164
- DD > 20%: 120
- Worst return: -29.61%
- Worst DD: 33.51%
- Mean return: 5.76%
- Mean DD: 20.08%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2007 | 263 | $-2,742.66 | 46.8% | $-10.43 |
| 2008 | 440 | $2,253.05 | 49.3% | $5.12 |
| 2009 | 467 | $-70.44 | 49.3% | $-0.15 |
| 2010 | 437 | $949.12 | 51.0% | $2.17 |
| 2011 | 423 | $-225.61 | 51.1% | $-0.53 |
| 2012 | 355 | $-2,259.74 | 46.5% | $-6.37 |
| 2013 | 350 | $-242.39 | 48.6% | $-0.69 |
| 2014 | 281 | $-1,027.25 | 46.3% | $-3.66 |
| 2015 | 388 | $1,852.92 | 49.7% | $4.78 |
| 2016 | 386 | $2,274.83 | 51.3% | $5.89 |
| 2017 | 288 | $2,656.41 | 51.0% | $9.22 |
| 2018 | 303 | $1,290.04 | 51.8% | $4.26 |
| 2019 | 234 | $0.96 | 47.9% | $0.00 |
| 2020 | 284 | $4,378.58 | 51.4% | $15.42 |
| 2021 | 273 | $-1,535.68 | 48.7% | $-5.63 |
| 2022 | 402 | $490.56 | 49.8% | $1.22 |
| 2023 | 330 | $2,185.95 | 49.1% | $6.62 |
| 2024 | 294 | $280.98 | 52.4% | $0.96 |
| 2025 | 303 | $-3,474.36 | 49.2% | $-11.47 |
| 2026 | 31 | $-87.33 | 51.6% | $-2.82 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2007 | +0 | +0 | -18 | +401 | -683 | -669 | -868 | -564 | -459 | +19 | +362 | -265 |
| 2008 | +195 | -356 | +539 | -34 | -180 | -163 | +430 | +2448 | -359 | -42 | -150 | -75 |
| 2009 | -822 | -604 | +1320 | -703 | +786 | -908 | -159 | +196 | +439 | +437 | -446 | +393 |
| 2010 | -340 | -769 | -773 | +140 | +1357 | +261 | -168 | +1148 | -853 | -365 | +1138 | +173 |
| 2011 | +858 | -1436 | +247 | -1149 | +525 | -109 | -417 | +305 | -423 | +1536 | -547 | +384 |
| 2012 | -943 | -24 | -344 | -545 | +289 | +1185 | -748 | -435 | +201 | -195 | -978 | +277 |
| 2013 | -730 | +184 | -326 | +190 | -162 | -174 | +375 | +96 | +26 | +307 | -101 | +73 |
| 2014 | +205 | -52 | -96 | +611 | -231 | -85 | -102 | -54 | -399 | -114 | -216 | -494 |
| 2015 | +704 | -503 | +529 | +936 | -287 | -285 | +51 | +544 | +212 | +1200 | -1023 | -224 |
| 2016 | +657 | -719 | +142 | -350 | -12 | -805 | -163 | +348 | +772 | +114 | +1702 | +590 |
| 2017 | -380 | -57 | +47 | +820 | +633 | -500 | +788 | -390 | -81 | +415 | +940 | +422 |
| 2018 | +2425 | +530 | +383 | +1359 | -1318 | -649 | -1093 | +121 | +234 | +976 | -1727 | +48 |
| 2019 | -965 | +786 | +96 | -921 | +412 | +542 | -479 | +571 | -563 | +380 | +474 | -333 |
| 2020 | -101 | +465 | +4301 | +284 | -524 | +744 | -52 | -1606 | +735 | +526 | -261 | -130 |
| 2021 | -872 | +375 | -388 | -0 | +601 | +1758 | +1094 | -1304 | -143 | -770 | -1420 | -467 |
| 2022 | -935 | +101 | -368 | -523 | +745 | +3376 | +1459 | -1308 | +1359 | +972 | -2892 | -1497 |
| 2023 | -1086 | -439 | +788 | -1184 | +1024 | -296 | +1346 | +176 | +153 | +6 | +835 | +863 |
| 2024 | +1868 | -804 | -1778 | -1545 | -1022 | +868 | -335 | -463 | -89 | +681 | +1667 | +1233 |
| 2025 | -1465 | -341 | -1028 | -1915 | -367 | +339 | +972 | -186 | -1111 | +173 | +882 | +575 |
| 2026 | -85 | -2 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2011-01-28
- Trough: 2015-01-14
- Recovery: 2017-05-26
- Max DD: 45.45%
- Duration: 2310 days
- Trades open: 1399
- Long/Short: 49.6% / 50.4%
- Top-2 symbol concentration: 42.6%
- Trades closed in plunge: 1397
- Win rate: 48.0%
- Avg PnL: $-3.67
- Max loss streak: 9

### Cluster 2
- Start: 2022-10-26
- Trough: 2025-04-14
- Recovery: ONGOING
- Max DD: 34.31%
- Duration: 1206 days
- Trades open: 820
- Long/Short: 49.4% / 50.6%
- Top-2 symbol concentration: 44.3%
- Trades closed in plunge: 816
- Win rate: 47.7%
- Avg PnL: $-9.34
- Max loss streak: 13

### Cluster 3
- Start: 2007-05-01
- Trough: 2007-10-18
- Recovery: 2008-10-14
- Max DD: 31.86%
- Duration: 532 days
- Trades open: 161
- Long/Short: 49.7% / 50.3%
- Top-2 symbol concentration: 46.0%
- Trades closed in plunge: 158
- Win rate: 41.1%
- Avg PnL: $-20.87
- Max loss streak: 7

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 17 | 13 |
| Avg Streak | 2.3 | 2.3 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $6,947.94 | 1.03 | 0.00% |
| Slip 1.0 pip RT | $-2,078.76 | 0.99 | 129.92% |
| Spread +50% | $921.85 | 1.00 | 86.73% |
| Severe (1.0 + 75%) | $-11,117.89 | 0.96 | 260.02% |

## Section 10 — Directional Robustness

- Total Longs: 3260
- Total Shorts: 3272
- Baseline PF: 1.03
- No Top-20 Longs PF: 0.99
- No Top-20 Shorts PF: 0.97
- No Both PF: 0.93

## Section 11 — Early/Late Split

**First Half** (3266 trades)
- CAGR: -2.78%
- Max DD: 45.48%
- Win Rate: 48.99%

**Second Half** (3266 trades)
- CAGR: 6.30%
- Max DD: 31.98%
- Win Rate: 50.24%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 5044 | 2.70% | 35.25% |
| EURUSD | 5287 | 2.54% | 32.92% |
| GBPUSD | 5436 | 1.75% | 48.82% |
| NZDUSD | 5449 | 2.05% | 39.30% |
| USDCAD | 5768 | 4.38% | 41.81% |
| USDCHF | 5676 | 0.56% | 57.10% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCHF | 856 | $5,832.99 | 42.1% | +84.0% |
| GBPUSD | 1096 | $3,071.77 | 54.1% | +44.2% |
| NZDUSD | 1083 | $2,276.11 | 52.8% | +32.8% |
| EURUSD | 1245 | $893.11 | 51.8% | +12.9% |
| AUDUSD | 1488 | $395.16 | 52.6% | +5.7% |
| USDCAD | 764 | $-5,521.20 | 37.7% | -79.5% |

## Section 14 — Block Bootstrap (100 runs)

- [SKIPPED] Block bootstrap failed: No backtest directories found for prefix: AK36_FX_PORTABILITY_4H

## Section 15 — Monthly Seasonality [FULL MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 18.54
- Kruskal-Wallis p-value: 0.0699
- Effect size (η²): 0.0012

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 571 | $-1,812.81 | 0.92 | — |
| 2 | 514 | $-3,665.16 | 0.81 | — |
| 3 | 504 | $3,271.61 | 1.18 | — |
| 4 | 555 | $-4,127.17 | 0.81 | — |
| 5 | 559 | $1,585.59 | 1.08 | — |
| 6 | 574 | $4,428.94 | 1.22 | — |
| 7 | 515 | $1,930.57 | 1.11 | — |
| 8 | 541 | $-357.70 | 0.98 | — |
| 9 | 556 | $-346.78 | 0.98 | — |
| 10 | 550 | $6,256.66 | 1.37 | — |
| 11 | 530 | $-1,759.32 | 0.92 | — |
| 12 | 563 | $1,543.51 | 1.08 | — |

## Section 16 — Weekday Seasonality [FULL MODE]

**Verdict:** Weak pattern detected (low effect size)
- Kruskal-Wallis H: 13.22
- Kruskal-Wallis p-value: 0.0103
- Effect size (η²): 0.0014

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 1217 | $-1,332.02 | 0.97 | — |
| 2 | 1394 | $11,841.76 | 1.26 | — |
| 3 | 1276 | $-2,254.17 | 0.95 | — |
| 4 | 1338 | $-3,433.74 | 0.93 | — |
| 5 | 1307 | $2,126.11 | 1.05 | — |
