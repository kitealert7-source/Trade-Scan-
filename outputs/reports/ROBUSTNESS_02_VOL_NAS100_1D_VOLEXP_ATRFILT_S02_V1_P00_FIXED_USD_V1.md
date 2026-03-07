# ROBUSTNESS REPORT — 02_VOL_NAS100_1D_VOLEXP_ATRFILT_S02_V1_P00 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 19:20:32

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 6 |
| Win Rate | 66.7% |
| Avg Win | $27.84 |
| Avg Loss | $2.37 |
| Payoff Ratio | 11.75 |
| Expectancy / Trade | $17.77 |
| Profit Factor | 23.49 |
| Net Profit | $106.62 |
| Max DD (USD) | $4.74 |
| Recovery Factor | 22.49 |

## Section 2 — Tail Contribution

- Top 1 trade: 43.19%
- Top 5 trades: 102.73%
- Top 1% (1): 43.19%
- Top 5% (1): 43.19%
- Total PnL: $106.62

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 2.56%
- New CAGR: 1.45%
- Degradation: 43.37%
- New Equity: $10,060.57

**Removing Top 5% (1 trades)**
- Original CAGR: 2.56%
- New CAGR: 1.45%
- Degradation: 43.37%
- New Equity: $10,060.57

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 2
- Regime Distribution: HIGH_VOL: 1, NORMAL: 1
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.02%
- Median CAGR: 0.03%
- 5th pctl CAGR: 0.00%
- 95th pctl CAGR: 0.03%
- Mean DD: 0.04%
- 95th pctl DD: 0.05%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 0.05%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 2.00% |
| 15.00% | 2.00% |
| 20.00% | 2.00% |
| 25.00% | 2.00% |
| 30.00% | 2.00% |

**Kelly Fraction**

- Full Kelly: 0.6383
- Safe fraction (½ Kelly): 0.3191

## Section 5 — Reverse Path Test

- Final Equity: $10,106.62
- CAGR: 2.56%
- Max DD: 0.05%
- Max Loss Streak: 2

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
| 2024 | 6 | $106.62 | 66.7% | $17.77 |

### Monthly PnL Heatmap

| Year | Feb | Mar | Apr | Jun |
|---|---|---|---|---|
| 2024 | +58 | +46 | -2 | +4 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-04-08
- Trough: 2024-06-04
- Recovery: 2024-06-27
- Max DD: 0.05%
- Duration: 80 days
- Trades open: 2
- Long/Short: 100.0% / 0.0%
- Top-2 symbol concentration: 100.0%
- Trades closed in plunge: 2
- Win rate: 0.0%
- Avg PnL: $-2.37
- Max loss streak: 2

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 3 | 2 |
| Avg Streak | 2.0 | 2.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $106.62 | 23.49 | 0.00% |
| Slip 1.0 pip RT | $106.02 | 22.46 | 0.56% |
| Spread +50% | $106.17 | 22.71 | 0.42% |
| Severe (1.0 + 75%) | $105.34 | 21.40 | 1.20% |

## Section 10 — Directional Robustness

- Total Longs: 6
- Total Shorts: 0
- Baseline PF: 23.49
- No Top-20 Longs PF: 23.49
- No Top-20 Shorts PF: 23.49
- No Both PF: 23.49

## Section 11 — Early/Late Split

**First Half** (3 trades)
- CAGR: 11.40%
- Max DD: 0.00%
- Win Rate: 100.00%

**Second Half** (3 trades)
- CAGR: 0.11%
- Max DD: 0.05%
- Win Rate: 33.33%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| NAS100 | 6 | $106.62 | 66.7% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 1.07%
- Median CAGR: 1.07%
- 5th pctl CAGR: 1.07%
- 95th pctl CAGR: 1.07%
- Mean DD: 0.05%
- Worst DD: 0.05%
- Runs ending below start: 0

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 6 trades < 300 threshold
- Dispersion: max deviation 28.28 from global mean 17.77

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 28.28 from global mean 17.77
