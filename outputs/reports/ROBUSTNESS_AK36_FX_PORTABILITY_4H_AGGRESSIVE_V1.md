# ROBUSTNESS REPORT — AK36_FX_PORTABILITY_4H / AGGRESSIVE_V1

Generated: 2026-02-25 12:41:47

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 3575 |
| Win Rate | 50.3% |
| Avg Win | $67.76 |
| Avg Loss | $71.94 |
| Payoff Ratio | 0.94 |
| Expectancy / Trade | $-1.72 |
| Profit Factor | 0.95 |
| Net Profit | $-5,796.06 |
| Max DD (USD) | $8,828.52 |
| Recovery Factor | -0.66 |

## Section 2 — Tail Contribution

- Top 1 trade: -21.54%
- Top 5 trades: -89.92%
- Top 1% (35): -317.33%
- Top 5% (178): -841.90%
- Total PnL: $-5,796.06

## Section 3 — Tail Removal

**Removing Top 1% (35 trades)**
- Original CAGR: -4.49%
- New CAGR: -100.00%
- Degradation: 2129.10%
- New Equity: $-14,188.59

**Removing Top 5% (178 trades)**
- Original CAGR: -4.49%
- New CAGR: -100.00%
- Degradation: 2129.10%
- New Equity: $-44,592.89

## Section 4 — Sequence Monte Carlo (500 runs)

- Mean CAGR: -0.03%
- Median CAGR: -0.03%
- 5th pctl CAGR: -0.03%
- 95th pctl CAGR: -0.03%
- Mean DD: 74.52%
- 95th pctl DD: 86.65%
- Blow-up runs (>90% DD): 7

## Section 5 — Reverse Path Test

- Final Equity: $4,912.11
- CAGR: -3.70%
- Max DD: 75.48%
- Max Loss Streak: 8

## Section 6 — Rolling 1-Year Window

- Total windows: 218
- Negative windows: 122
- Return < -10%: 78
- DD > 15%: 182
- DD > 20%: 145
- Worst return: -45.14%
- Worst DD: 50.83%
- Mean return: -1.13%
- Mean DD: 25.69%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2007 | 146 | $-3,385.49 | 52.1% | $-23.19 |
| 2008 | 272 | $3,368.59 | 49.6% | $12.38 |
| 2009 | 300 | $-1,180.76 | 50.0% | $-3.94 |
| 2010 | 261 | $-1,235.83 | 48.3% | $-4.73 |
| 2011 | 234 | $244.52 | 50.0% | $1.04 |
| 2012 | 173 | $-3,076.27 | 41.6% | $-17.78 |
| 2013 | 183 | $-860.10 | 50.3% | $-4.70 |
| 2014 | 144 | $-966.43 | 50.7% | $-6.71 |
| 2015 | 211 | $528.11 | 50.7% | $2.50 |
| 2016 | 204 | $374.76 | 50.5% | $1.84 |
| 2017 | 151 | $537.32 | 51.7% | $3.56 |
| 2018 | 143 | $178.08 | 53.1% | $1.25 |
| 2019 | 122 | $418.45 | 54.1% | $3.43 |
| 2020 | 148 | $1,025.60 | 48.0% | $6.93 |
| 2021 | 138 | $270.89 | 55.1% | $1.96 |
| 2022 | 230 | $-316.04 | 50.9% | $-1.37 |
| 2023 | 173 | $939.69 | 49.1% | $5.43 |
| 2024 | 152 | $-1,281.38 | 52.6% | $-8.43 |
| 2025 | 175 | $-1,125.83 | 51.4% | $-6.43 |
| 2026 | 15 | $-253.94 | 46.7% | $-16.93 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2007 | +0 | +0 | -49 | -163 | -438 | -677 | -351 | -1173 | -680 | -68 | +978 | -764 |
| 2008 | -37 | -853 | +856 | +248 | -375 | +62 | +637 | +2683 | -54 | -366 | -152 | +720 |
| 2009 | -1371 | -991 | +2432 | -1783 | +921 | -1450 | +93 | +124 | +693 | +119 | -244 | +275 |
| 2010 | -436 | -386 | -1312 | -227 | +1653 | -206 | -113 | +470 | -375 | -905 | +356 | +244 |
| 2011 | +543 | -535 | +298 | -796 | +552 | -50 | -538 | -222 | -178 | +1730 | -460 | -98 |
| 2012 | -1289 | -203 | -891 | -330 | -271 | +407 | -609 | -242 | +508 | -104 | -238 | +186 |
| 2013 | -538 | +252 | -295 | -227 | -180 | -29 | +140 | -79 | -122 | +47 | +127 | +43 |
| 2014 | -336 | +62 | -37 | +294 | +52 | -175 | -100 | +45 | -334 | -217 | -88 | -133 |
| 2015 | -38 | -195 | +405 | +524 | -140 | +36 | -157 | +113 | -39 | +694 | -133 | -544 |
| 2016 | +97 | -10 | -264 | -118 | +125 | +204 | +3 | -21 | +120 | +39 | +55 | +145 |
| 2017 | +171 | +20 | +157 | +169 | +85 | -247 | -59 | -74 | -108 | +38 | +131 | +256 |
| 2018 | +504 | +205 | -204 | +521 | +4 | -321 | -131 | +20 | +141 | -113 | -424 | -25 |
| 2019 | -278 | +358 | -36 | +172 | +343 | +241 | -306 | -54 | -99 | -39 | +200 | -84 |
| 2020 | -351 | +379 | +1570 | +242 | -344 | +224 | +265 | -1084 | +360 | +268 | -392 | -112 |
| 2021 | -119 | -306 | +48 | -126 | +15 | +530 | +363 | -316 | +251 | -126 | -378 | +433 |
| 2022 | -581 | -48 | -785 | -442 | +190 | +869 | +601 | -302 | +864 | +446 | -996 | -131 |
| 2023 | -179 | -383 | +296 | -442 | +429 | -16 | +416 | +164 | -130 | -432 | +664 | +553 |
| 2024 | +370 | -123 | -691 | -416 | -421 | +154 | -328 | -614 | -110 | +292 | +614 | -9 |
| 2025 | -129 | +43 | -539 | -1134 | -68 | +277 | +298 | -3 | -213 | +160 | +115 | +68 |
| 2026 | +41 | -295 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2008-10-23
- Trough: 2015-01-22
- Recovery: ONGOING
- Max DD: 76.98%
- Duration: 6322 days
- Trades open: 1375
- Long/Short: 49.5% / 50.5%
- Top-2 symbol concentration: 48.1%
- Trades closed in plunge: 1371
- Win rate: 48.4%
- Avg PnL: $-6.44
- Max loss streak: 8

### Cluster 2
- Start: 2007-03-29
- Trough: 2008-02-22
- Recovery: 2008-09-29
- Max DD: 42.76%
- Duration: 550 days
- Trades open: 192
- Long/Short: 47.4% / 52.6%
- Top-2 symbol concentration: 56.8%
- Trades closed in plunge: 191
- Win rate: 49.2%
- Avg PnL: $-22.39
- Max loss streak: 7

### Cluster 3
- Start: 2008-09-30
- Trough: 2008-10-01
- Recovery: 2008-10-08
- Max DD: 5.98%
- Duration: 8 days
- Trades open: 6
- Long/Short: 66.7% / 33.3%
- Top-2 symbol concentration: 66.7%
- Trades closed in plunge: 3
- Win rate: 0.0%
- Avg PnL: $-107.77
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 14 | 8 |
| Avg Streak | 2.2 | 2.2 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-5,796.06 | 0.95 | 0.00% |
| Slip 1.0 pip RT | $-9,867.16 | 0.92 | -70.24% |
| Spread +50% | $-8,509.36 | 0.93 | -46.81% |
| Severe (1.0 + 75%) | $-13,937.12 | 0.89 | -140.46% |

## Section 10 — Directional Robustness

- Total Longs: 1768
- Total Shorts: 1807
- Baseline PF: 0.95
- No Top-20 Longs PF: 0.88
- No Top-20 Shorts PF: 0.87
- No Both PF: 0.80

## Section 11 — Early/Late Split

**First Half** (1787 trades)
- CAGR: -12.28%
- Max DD: 77.16%
- Win Rate: 49.30%

**Second Half** (1788 trades)
- CAGR: 0.65%
- Max DD: 26.56%
- Win Rate: 51.23%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 2550 | -3.21% | 63.03% |
| EURUSD | 2954 | -4.57% | 70.26% |
| GBPUSD | 3129 | -8.80% | 89.92% |
| NZDUSD | 2898 | -1.78% | 51.98% |
| USDCAD | 3201 | -2.16% | 65.83% |
| USDCHF | 3143 | -2.70% | 69.07% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| GBPUSD | 446 | $2,446.51 | 57.8% | -42.2% |
| EURUSD | 621 | $68.81 | 53.8% | -1.2% |
| AUDUSD | 1025 | $-1,201.75 | 53.8% | +20.7% |
| USDCHF | 432 | $-1,765.60 | 38.9% | +30.5% |
| USDCAD | 374 | $-2,424.44 | 37.4% | +41.8% |
| NZDUSD | 677 | $-2,919.59 | 51.1% | +50.4% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -0.60%
- Median CAGR: -0.94%
- 5th pctl CAGR: -4.93%
- 95th pctl CAGR: 4.20%
- Mean DD: 49.24%
- Worst DD: 77.87%
- Runs ending below start: 28
