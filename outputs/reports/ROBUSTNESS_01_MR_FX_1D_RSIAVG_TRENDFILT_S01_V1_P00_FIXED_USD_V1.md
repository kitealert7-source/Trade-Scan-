# ROBUSTNESS REPORT — 01_MR_FX_1D_RSIAVG_TRENDFILT_S01_V1_P00 / FIXED_USD_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 16:06:48

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 2 |
| Win Rate | 100.0% |
| Avg Win | $42.59 |
| Avg Loss | $0.00 |
| Payoff Ratio | 999.00 |
| Expectancy / Trade | $42.59 |
| Profit Factor | 999.00 |
| Net Profit | $85.17 |
| Max DD (USD) | $0.00 |
| Recovery Factor | 999.00 |

## Section 2 — Tail Contribution

- Top 1 trade: 61.90%
- Top 5 trades: 100.00%
- Top 1% (1): 61.90%
- Top 5% (1): 61.90%
- Total PnL: $85.17

## Section 3 — Tail Removal

**Removing Top 1% (1 trades)**
- Original CAGR: 12.88%
- New CAGR: 4.74%
- Degradation: 63.22%
- New Equity: $10,032.45

**Removing Top 5% (1 trades)**
- Original CAGR: 12.88%
- New CAGR: 4.74%
- Degradation: 63.22%
- New Equity: $10,032.45

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 1
- Regime Distribution: NORMAL: 1
- Simulations: 500
- Seed: 42

- Mean CAGR: 0.12%
- Median CAGR: 0.12%
- 5th pctl CAGR: 0.12%
- 95th pctl CAGR: 0.12%
- Mean DD: 0.00%
- 95th pctl DD: 0.00%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 0.00%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.50% |
| 15.00% | 0.50% |
| 20.00% | 0.50% |
| 25.00% | 0.50% |
| 30.00% | 0.50% |

**Kelly Fraction**

- Full Kelly: 1.0000
- Safe fraction (½ Kelly): 0.5000

## Section 5 — Reverse Path Test

- Final Equity: $10,085.17
- CAGR: 12.16%
- Max DD: 0.00%
- Max Loss Streak: 0

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
| 2024 | 2 | $85.17 | 100.0% | $42.59 |

### Monthly PnL Heatmap

| Year | Jun |
|---|---|
| 2024 | +85 |

## Section 7 — Drawdown Diagnostics

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 2 | 0 |
| Avg Streak | 2.0 | 0.0 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $85.17 | 999.00 | 0.00% |
| Slip 1.0 pip RT | $84.97 | 999.00 | 0.23% |
| Spread +50% | $85.02 | 999.00 | 0.18% |
| Severe (1.0 + 75%) | $84.75 | 999.00 | 0.50% |

## Section 10 — Directional Robustness

- Total Longs: 2
- Total Shorts: 0
- Baseline PF: 999.00
- No Top-20 Longs PF: 999.00
- No Top-20 Shorts PF: 999.00
- No Both PF: 999.00

## Section 11 — Early/Late Split

**First Half** (1 trades)
- CAGR: 46.83%
- Max DD: 0.00%
- Win Rate: 100.00%

**Second Half** (1 trades)
- CAGR: 48.36%
- Max DD: 0.00%
- Win Rate: 100.00%

## Section 12 — Symbol Isolation Stress

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| NAS100 | 2 | $85.17 | 100.0% | +100.0% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: 0.85%
- Median CAGR: 0.85%
- 5th pctl CAGR: 0.85%
- 95th pctl CAGR: 0.85%
- Mean DD: 0.00%
- Worst DD: 0.00%
- Runs ending below start: 0

## Section 15 — Monthly Seasonality [SHORT MODE]

- SUPPRESSED: 2 trades < 300 threshold
- Dispersion: max deviation 0.00 from global mean 42.59

## Section 16 — Weekday Seasonality [SHORT MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 10.13 from global mean 42.59
