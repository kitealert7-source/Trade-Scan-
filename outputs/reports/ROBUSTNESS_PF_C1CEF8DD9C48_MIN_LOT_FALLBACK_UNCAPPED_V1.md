# ROBUSTNESS REPORT — PF_C1CEF8DD9C48 / MIN_LOT_FALLBACK_UNCAPPED_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-18 06:14:04

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 217 |
| Win Rate | 63.1% |
| Avg Win | $42.45 |
| Avg Loss | $47.43 |
| Payoff Ratio | 0.90 |
| Expectancy / Trade | $9.32 |
| Profit Factor | 1.53 |
| Net Profit | $2,021.72 |
| Max DD (USD) | $627.98 |
| Recovery Factor | 3.22 |

## Section 2 — Tail Contribution

- Top 1 trade: 17.42%
- Top 5 trades: 55.25%
- Top 1% (2): 30.13%
- Top 5% (10): 87.22%
- Total PnL: $2,021.72

## Section 3 — Tail Removal

**Removing Top 1% (2 trades)**
- Original CAGR: 8.81%
- New CAGR: 6.25%
- Degradation: 29.10%
- New Equity: $11,412.52

**Removing Top 5% (10 trades)**
- Original CAGR: 8.81%
- New CAGR: 1.18%
- Degradation: 86.64%
- New Equity: $10,258.46

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 1
- Regime Distribution: NORMAL: 1
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.09%
- Median CAGR: 0.09%
- 5th pctl CAGR: 0.09%
- 95th pctl CAGR: 0.09%
- Mean DD: 5.73%
- 95th pctl DD: 5.73%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 5.73%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.87% |
| 15.00% | 1.31% |
| 20.00% | 1.74% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.2195
- Safe fraction (½ Kelly): 0.1097

## Section 5 — Reverse Path Test

- Final Equity: $12,016.83
- CAGR: 8.80%
- Max DD: 5.77%
- Max Loss Streak: 5

## Section 6 — Rolling 1-Year Window

- Total windows: 15
- Negative windows: 4
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -2.74%
- Worst DD: 5.73%
- Mean return: 4.64%
- Mean DD: 4.96%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 93 | $854.70 | 63.4% | $9.19 |
| 2025 | 98 | $750.20 | 61.2% | $7.66 |
| 2026 | 26 | $416.82 | 69.2% | $16.03 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +117 | +199 | +300 | +69 | -43 | +87 | -72 | -38 | -21 | +4 | +207 | +46 |
| 2025 | +36 | -489 | +73 | -83 | +226 | +227 | +8 | +246 | +97 | +39 | +111 | +258 |
| 2026 | +461 | +464 | -508 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-12-10
- Trough: 2025-03-07
- Recovery: 2025-08-07
- Max DD: 5.73%
- Duration: 240 days
- Trades open: 40
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 62.5%
- Trades closed in plunge: 40
- Win rate: 45.0%
- Avg PnL: $-14.83
- Max loss streak: 5

### Cluster 2
- Start: 2026-03-02
- Trough: 2026-03-09
- Recovery: ONGOING
- Max DD: 4.05%
- Duration: 7 days
- Trades open: 4
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 75.0%
- Trades closed in plunge: 4
- Win rate: 0.0%
- Avg PnL: $-126.99
- Max loss streak: 4

### Cluster 3
- Start: 2024-07-17
- Trough: 2024-10-28
- Recovery: 2024-11-22
- Max DD: 2.47%
- Duration: 128 days
- Trades open: 24
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 62.5%
- Trades closed in plunge: 23
- Win rate: 52.2%
- Avg PnL: $-11.60
- Max loss streak: 3

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 12 | 5 |
| Avg Streak | 2.9 | 1.7 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $2,021.72 | 1.53 | 0.00% |
| Slip 1.0 pip RT | $2,021.70 | 1.53 | 0.00% |
| Spread +50% | $2,021.70 | 1.53 | 0.00% |
| Severe (1.0 + 75%) | $2,021.67 | 1.53 | 0.00% |

## Section 10 — Directional Robustness

- Total Longs: 217
- Total Shorts: 0
- Baseline PF: 1.53
- No Top-20 Longs PF: 0.81
- No Top-20 Shorts PF: 1.53
- No Both PF: 0.81

## Section 11 — Early/Late Split

**First Half** (108 trades)
- CAGR: 8.28%
- Max DD: 2.47%
- Win Rate: 64.81%

**Second Half** (109 trades)
- CAGR: 10.15%
- Max DD: 6.01%
- Win Rate: 61.47%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUS200 | 170 | 8.02% | 5.53% |
| JPN225 | 171 | 4.64% | 3.34% |
| US30 | 166 | 6.36% | 5.13% |
| XAUUSD | 144 | 7.72% | 4.85% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| JPN225 | 46 | $983.25 | 56.5% | +48.6% |
| US30 | 51 | $583.65 | 64.7% | +28.9% |
| XAUUSD | 73 | $263.35 | 67.1% | +13.0% |
| AUS200 | 47 | $191.47 | 61.7% | +9.5% |

## Section 14 — Block Bootstrap (100 runs)

- [SKIPPED] Block bootstrap failed: [Errno 2] No such file or directory: 'strategies\\PF_C1CEF8DD9C48\\deployable\\MIN_LOT_FALLBACK_UNCAPPED_V1\\deployable_trade_log.csv'

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 217 trades < 300 threshold
- Dispersion: max deviation 15.75 from global mean 9.32

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 22.18 from global mean 9.32
