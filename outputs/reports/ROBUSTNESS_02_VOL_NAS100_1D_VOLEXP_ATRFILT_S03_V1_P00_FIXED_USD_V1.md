# ROBUSTNESS REPORT — 02_VOL_NAS100_1D_VOLEXP_ATRFILT_S03_V1_P00 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 19:20:39

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 4 |
| Win Rate | 75.0% |
| Avg Win | $29.12 |
| Avg Loss | $2.64 |
| Payoff Ratio | 11.03 |
| Expectancy / Trade | $21.18 |
| Profit Factor | 33.09 |
| Net Profit | $84.72 |
| Max DD (USD) | $2.64 |
| Recovery Factor | 32.09 |

## Section 2 — Tail Contribution

- Top 1 trade: 54.36%
- Top 5 trades: 100.00%
- Top 1% (1): 54.36%
- Top 5% (1): 54.36%
- Total PnL: $84.72

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 2.59%
- New CAGR: 1.18%
- Degradation: 54.57%
- New Equity: $10,038.67

**Removing Top 5% (1 trades)**
- Original CAGR: 2.59%
- New CAGR: 1.18%
- Degradation: 54.57%
- New Equity: $10,038.67

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 1
- Regime Distribution: NORMAL: 1
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.03%
- Median CAGR: 0.03%
- 5th pctl CAGR: 0.03%
- 95th pctl CAGR: 0.03%
- Mean DD: 0.03%
- 95th pctl DD: 0.03%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 0.03%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 2.00% |
| 15.00% | 2.00% |
| 20.00% | 2.00% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.7273
- Safe fraction (½ Kelly): 0.3637

## Section 5 — Reverse Path Test

- Final Equity: $10,084.72
- CAGR: 2.58%
- Max DD: 0.03%
- Max Loss Streak: 1

## Section 6 — Rolling 1-Year Window

- Total windows: 0
- Negative windows: 0
- Return < -10%: 0
- DD > 15%: 0
- DD > 20%: 0
- Worst return: 0.00%
- Worst DD: 0.00%
- Mean return: 0.00%
- Mean DD: 0.00%
- Negative clustering: N/A

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 4 | $84.72 | 75.0% | $21.18 |

### Monthly PnL Heatmap

| Year | Mar | Apr | Jun |
|---|---|---|---|
| 2024 | +46 | +6 | +33 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-06-28
- Trough: 2024-06-28
- Recovery: ONGOING
- Max DD: 0.03%
- Duration: 0 days
- Trades open: 1
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 1
- Win rate: 0.0%
- Avg PnL: $-2.64
- Max loss streak: 1

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 3 | 1 |
| Avg Streak | 3.0 | 1.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $84.72 | 33.09 | 0.00% |
| Slip 1.0 pip RT | $84.32 | 31.77 | 0.47% |
| Spread +50% | $84.42 | 32.09 | 0.35% |
| Severe (1.0 + 75%) | $83.87 | 30.40 | 1.00% |

## Section 10 — Directional Robustness

- Total Longs: 4
- Total Shorts: 0
- Baseline PF: 33.09
- No Top-20 Longs PF: 33.09
- No Top-20 Shorts PF: 33.09
- No Both PF: 33.09

## Section 11 — Early/Late Split

**First Half** (2 trades)
- CAGR: 4.71%
- Max DD: 0.00%
- Win Rate: 100.00%

**Second Half** (2 trades)
- CAGR: 4.09%
- Max DD: 0.03%
- Win Rate: 50.00%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| NAS100 | 4 | $84.72 | 75.0% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 0.85%
- Median CAGR: 0.85%
- 5th pctl CAGR: 0.85%
- 95th pctl CAGR: 0.85%
- Mean DD: 0.03%
- Worst DD: 0.03%
- Runs ending below start: 0

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 4 trades < 300 threshold
- Dispersion: max deviation 24.87 from global mean 21.18

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 15.45 from global mean 21.18
