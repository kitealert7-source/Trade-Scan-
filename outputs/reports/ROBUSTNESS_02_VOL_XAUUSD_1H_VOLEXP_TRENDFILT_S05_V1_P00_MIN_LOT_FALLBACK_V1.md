# ROBUSTNESS REPORT — 02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S05_V1_P00 / MIN_LOT_FALLBACK_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-18 05:53:23

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 73 |
| Win Rate | 67.1% |
| Avg Win | $24.07 |
| Avg Loss | $38.17 |
| Payoff Ratio | 0.63 |
| Expectancy / Trade | $3.61 |
| Profit Factor | 1.29 |
| Net Profit | $263.35 |
| Max DD (USD) | $202.06 |
| Recovery Factor | 1.30 |

## Section 2 — Tail Contribution

- Top 1 trade: 30.12%
- Top 5 trades: 126.37%
- Top 1% (1): 30.12%
- Top 5% (3): 80.99%
- Total PnL: $263.35

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 1.26%
- New CAGR: 0.88%
- Degradation: 29.98%
- New Equity: $10,184.03

**Removing Top 5% (3 trades)**
- Original CAGR: 1.26%
- New CAGR: 0.24%
- Degradation: 80.89%
- New Equity: $10,050.06

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 1
- Regime Distribution: NORMAL: 1
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.01%
- Median CAGR: 0.01%
- 5th pctl CAGR: 0.01%
- 95th pctl CAGR: 0.01%
- Mean DD: 1.99%
- 95th pctl DD: 1.99%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 1.99%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 2.00% |
| 15.00% | 2.00% |
| 20.00% | 2.00% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.1499
- Safe fraction (½ Kelly): 0.0749

## Section 5 — Reverse Path Test

- Final Equity: $10,263.35
- CAGR: 1.27%
- Max DD: 1.99%
- Max Loss Streak: 3

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 6
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: -0.93%
- Worst DD: 1.99%
- Mean return: 0.34%
- Mean DD: 1.73%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 29 | $89.62 | 65.5% | $3.09 |
| 2025 | 39 | $114.73 | 66.7% | $2.94 |
| 2026 | 5 | $59.00 | 80.0% | $11.80 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | -47 | +3 | +68 | +89 | +0 | -70 | +90 | -38 | +3 | +16 | -40 | +15 |
| 2025 | -19 | -111 | +19 | +59 | +17 | +37 | +0 | +72 | -69 | +16 | +17 | +77 |
| 2026 | +3 | +56 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-09-27
- Trough: 2025-03-07
- Recovery: 2025-08-05
- Max DD: 1.99%
- Duration: 312 days
- Trades open: 20
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 20
- Win rate: 50.0%
- Avg PnL: $-8.37
- Max loss streak: 3

### Cluster 2
- Start: 2024-04-08
- Trough: 2024-07-09
- Recovery: 2024-09-24
- Max DD: 1.37%
- Duration: 169 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 5
- Win rate: 40.0%
- Avg PnL: $-19.72
- Max loss streak: 2

### Cluster 3
- Start: 2025-09-01
- Trough: 2025-10-02
- Recovery: 2025-12-22
- Max DD: 0.83%
- Duration: 112 days
- Trades open: 5
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 4
- Win rate: 50.0%
- Avg PnL: $-17.17
- Max loss streak: 1

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 3 |
| Avg Streak | 2.9 | 1.4 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $263.35 | 1.29 | 0.00% |
| Slip 1.0 pip RT | $263.33 | 1.29 | 0.01% |
| Spread +50% | $263.33 | 1.29 | 0.01% |
| Severe (1.0 + 75%) | $263.31 | 1.29 | 0.02% |

## Section 10 — Directional Robustness

- Total Longs: 73
- Total Shorts: 0
- Baseline PF: 1.29
- No Top-20 Longs PF: 0.35
- No Top-20 Shorts PF: 1.29
- No Both PF: 0.35

## Section 11 — Early/Late Split

**First Half** (36 trades)
- CAGR: 0.69%
- Max DD: 1.47%
- Win Rate: 63.89%

**Second Half** (37 trades)
- CAGR: 1.91%
- Max DD: 1.42%
- Win Rate: 70.27%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| XAUUSD | 73 | $263.35 | 67.1% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- [SKIPPED] Block bootstrap failed: [Errno 2] No such file or directory: 'strategies\\02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S05_V1_P00\\deployable\\MIN_LOT_FALLBACK_V1\\deployable_trade_log.csv'

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 73 trades < 300 threshold
- Dispersion: max deviation 19.38 from global mean 3.61

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 7.92 from global mean 3.61
