# ROBUSTNESS REPORT — 02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P00 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-18 05:53:16

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 314 |
| Win Rate | 62.7% |
| Avg Win | $20.52 |
| Avg Loss | $21.13 |
| Payoff Ratio | 0.97 |
| Expectancy / Trade | $5.00 |
| Profit Factor | 1.63 |
| Net Profit | $1,569.44 |
| Max DD (USD) | $285.78 |
| Recovery Factor | 5.49 |

## Section 2 — Tail Contribution

- Top 1 trade: 5.75%
- Top 5 trades: 21.02%
- Top 1% (3): 13.48%
- Top 5% (15): 53.87%
- Total PnL: $1,569.44

## Section 3 — Tail Removal

**Removing Top 1% (3 trades)**
- Original CAGR: 6.88%
- New CAGR: 5.99%
- Degradation: 13.03%
- New Equity: $11,357.84

**Removing Top 5% (15 trades)**
- Original CAGR: 6.88%
- New CAGR: 3.24%
- Degradation: 52.88%
- New Equity: $10,723.99

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 1
- Regime Distribution: NORMAL: 1
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.07%
- Median CAGR: 0.07%
- 5th pctl CAGR: 0.07%
- 95th pctl CAGR: 0.07%
- Mean DD: 2.41%
- 95th pctl DD: 2.41%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 2.41%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 2.00% |
| 15.00% | 2.00% |
| 20.00% | 2.00% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.2436
- Safe fraction (½ Kelly): 0.1218

## Section 5 — Reverse Path Test

- Final Equity: $11,572.48
- CAGR: 6.90%
- Max DD: 2.43%
- Max Loss Streak: 9

## Section 6 — Rolling 1-Year Window

- Total windows: 15
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 4.14%
- Worst DD: 2.13%
- Mean return: 6.64%
- Mean DD: 2.00%
- Negative clustering: N/A (No negative windows)

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 175 | $1,023.80 | 60.6% | $5.85 |
| 2025 | 108 | $691.23 | 67.6% | $6.40 |
| 2026 | 31 | $-145.59 | 58.1% | $-4.70 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +52 | +476 | +327 | -51 | -160 | -5 | +131 | -27 | +117 | +123 | +151 | -112 |
| 2025 | +181 | +68 | +29 | +0 | +18 | +75 | +240 | -34 | +66 | -69 | +51 | +66 |
| 2026 | +19 | +122 | -286 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2026-03-04
- Trough: 2026-03-13
- Recovery: ONGOING
- Max DD: 2.41%
- Duration: 9 days
- Trades open: 7
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 57.1%
- Trades closed in plunge: 7
- Win rate: 0.0%
- Avg PnL: $-40.83
- Max loss streak: 7

### Cluster 2
- Start: 2024-12-10
- Trough: 2024-12-23
- Recovery: 2025-01-30
- Max DD: 2.13%
- Duration: 51 days
- Trades open: 14
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 42.9%
- Trades closed in plunge: 11
- Win rate: 9.1%
- Avg PnL: $-21.60
- Max loss streak: 6

### Cluster 3
- Start: 2024-04-02
- Trough: 2024-06-14
- Recovery: 2024-10-01
- Max DD: 2.11%
- Duration: 182 days
- Trades open: 33
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 30.3%
- Trades closed in plunge: 33
- Win rate: 36.4%
- Avg PnL: $-6.93
- Max loss streak: 6

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 15 | 9 |
| Avg Streak | 4.2 | 2.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $1,569.44 | 1.63 | 0.00% |
| Slip 1.0 pip RT | $1,569.43 | 1.63 | 0.00% |
| Spread +50% | $1,569.43 | 1.63 | 0.00% |
| Severe (1.0 + 75%) | $1,569.42 | 1.63 | 0.00% |

## Section 10 — Directional Robustness

- Total Longs: 314
- Total Shorts: 0
- Baseline PF: 1.63
- No Top-20 Longs PF: 1.20
- No Top-20 Shorts PF: 1.63
- No Both PF: 1.20

## Section 11 — Early/Late Split

**First Half** (157 trades)
- CAGR: 12.72%
- Max DD: 2.11%
- Win Rate: 63.69%

**Second Half** (157 trades)
- CAGR: 3.35%
- Max DD: 2.67%
- Win Rate: 61.78%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUS200 | 267 | 6.07% | 2.13% |
| ESP35 | 274 | 5.86% | 2.46% |
| EUSTX50 | 263 | 5.44% | 2.15% |
| FRA40 | 258 | 6.69% | 1.92% |
| GER40 | 293 | 6.59% | 2.42% |
| NAS100 | 304 | 6.35% | 2.44% |
| SPX500 | 273 | 5.55% | 2.66% |
| UK100 | 266 | 5.88% | 1.97% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| EUSTX50 | 51 | $339.72 | 64.7% | +21.6% |
| SPX500 | 41 | $320.52 | 58.5% | +20.4% |
| ESP35 | 40 | $241.12 | 62.5% | +15.4% |
| UK100 | 48 | $235.69 | 64.6% | +15.0% |
| AUS200 | 47 | $191.47 | 61.7% | +12.2% |
| NAS100 | 10 | $126.31 | 80.0% | +8.0% |
| GER40 | 21 | $69.85 | 71.4% | +4.5% |
| FRA40 | 56 | $44.76 | 57.1% | +2.9% |

## Section 14 — Block Bootstrap (100 runs)

- [SKIPPED] Block bootstrap failed: [Errno 2] No such file or directory: 'strategies\\02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P00\\deployable\\FIXED_USD_V1\\deployable_trade_log.csv'

## Section 15 — Monthly Seasonality [MEDIUM MODE]

**Verdict:** Significant calendar pattern
- Kruskal-Wallis H: 27.51
- Kruskal-Wallis p-value: 0.0038
- Effect size (η²): 0.0547

| Bucket | Trades | Net PnL | PF | Flag |
|---|---|---|---|---|
| 1 | 45 | $251.62 | 1.63 | — |
| 2 | 40 | $666.01 | 5.08 | — |
| 3 | 23 | $70.98 | 1.22 | — |
| 4 | 9 | $-51.19 | 0.15 | — |
| 5 | 15 | $-142.26 | 0.27 | — |
| 6 | 29 | $70.11 | 1.28 | — |
| 7 | 32 | $371.64 | 5.86 | — |
| 8 | 16 | $-60.87 | 0.70 | — |
| 9 | 31 | $182.60 | 1.87 | — |
| 10 | 28 | $54.48 | 1.29 | — |
| 11 | 21 | $201.95 | 2.76 | — |
| 12 | 25 | $-45.63 | 0.84 | — |

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 11.77 from global mean 5.00
