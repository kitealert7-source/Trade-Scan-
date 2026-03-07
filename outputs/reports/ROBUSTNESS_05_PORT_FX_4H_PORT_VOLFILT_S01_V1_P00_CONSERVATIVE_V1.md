# ROBUSTNESS REPORT — 05_PORT_FX_4H_PORT_VOLFILT_S01_V1_P00 / CONSERVATIVE_V1

Engine: Robustness v2.2.0 | Generated: 2026-03-07 19:07:17

## Section 1 — Edge Metrics Summary

| Metric | Value |
|---|---|
| Total Trades | 226 |
| Win Rate | 39.8% |
| Avg Win | $49.20 |
| Avg Loss | $38.55 |
| Payoff Ratio | 1.28 |
| Expectancy / Trade | $-3.60 |
| Profit Factor | 0.84 |
| Net Profit | $-814.68 |
| Max DD (USD) | $1,698.89 |
| Recovery Factor | -0.48 |

## Section 2 — Tail Contribution

- Top 1 trade: -54.52%
- Top 5 trades: -125.71%
- Top 1% (2): -74.25%
- Top 5% (11): -212.78%
- Total PnL: $-814.68

## Section 3 — Tail Removal

**Removing Top 1% (2 trades)**
- Original CAGR: -3.91%
- New CAGR: -6.94%
- Degradation: 77.33%
- New Equity: $8,580.46

**Removing Top 5% (11 trades)**
- Original CAGR: -3.91%
- New CAGR: -12.90%
- Degradation: 229.78%
- New Equity: $7,451.82

## Section 4 — Monte Carlo Simulation

- Method: **REGIME_AWARE_BLOCK_BOOTSTRAP**
- Block Definition: contiguous_regime_segments
- Total Regime Blocks: 24
- Regime Distribution: HIGH_VOL: 4, LOW_VOL: 8, NORMAL: 12
- Simulations: 500
- Seed: 42

- Mean CAGR: -0.03%
- Median CAGR: -0.04%
- 5th pctl CAGR: -0.11%
- 95th pctl CAGR: 0.05%
- Mean DD: 15.53%
- 95th pctl DD: 25.73%
- Blow-up runs (>90% DD): 0

## Section 4.5 — Position Sizing Guidance

Current capital model risk assumption: 0.50%

**Monte Carlo Drawdown Distribution**
- 95th pctl DD: 25.73%

**Suggested Risk Levels**

| Target Max DD | Suggested Risk |
|---|---|
| 10.00% | 0.19% |
| 15.00% | 0.29% |
| 20.00% | 0.39% |
| 25.00% | 0.49% |
| 30.00% | 0.58% |

**Kelly Fraction**

- Full Kelly: 0.0000
- Safe fraction (½ Kelly): 0.0000

## Section 5 — Reverse Path Test

- Final Equity: $9,229.72
- CAGR: -3.69%
- Max DD: 16.24%
- Max Loss Streak: 14

## Section 6 — Rolling 1-Year Window

- Total windows: 14
- Negative windows: 12
- Return < -10%: 0
- DD > 15%: 4
- DD > 20%: 0
- Worst return: -9.28%
- Worst DD: 15.04%
- Mean return: -5.08%
- Mean DD: 12.54%
- Negative clustering: CLUSTERED

### Year-Wise PnL

| Year | Trades | Net PnL | Win Rate | Avg PnL |
|---|---|---|---|---|
| 2024 | 111 | $4.68 | 40.5% | $0.04 |
| 2025 | 99 | $-928.61 | 37.4% | $-9.38 |
| 2026 | 16 | $109.25 | 50.0% | $6.83 |

### Monthly PnL Heatmap

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | +0 | +0 | -117 | -263 | -222 | -305 | +51 | +144 | -223 | +654 | +286 |
| 2025 | -287 | -289 | +18 | -569 | +95 | +193 | -338 | -29 | -298 | +418 | +158 |
| 2026 | -100 | +210 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 | +0 |

## Section 7 — Drawdown Diagnostics

### Cluster 1
- Start: 2024-03-15
- Trough: 2025-09-25
- Recovery: ONGOING
- Max DD: 16.66%
- Duration: 706 days
- Trades open: 195
- Long/Short: 50.3% / 49.7%
- Top-2 symbol concentration: 36.9%
- Trades closed in plunge: 192
- Win rate: 36.5%
- Avg PnL: $-8.85
- Max loss streak: 14

## Section 8 — Streak Analysis

| Metric | Wins | Losses |
|---|---|---|
| Max Streak | 8 | 14 |
| Avg Streak | 2.2 | 3.3 |

## Section 9 — Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $-814.68 | 0.84 | 0.00% |
| Slip 1.0 pip RT | $-912.68 | 0.83 | -12.03% |
| Spread +50% | $-881.57 | 0.83 | -8.21% |
| Severe (1.0 + 75%) | $-1,013.01 | 0.81 | -24.35% |

## Section 10 — Directional Robustness

- Total Longs: 111
- Total Shorts: 115
- Baseline PF: 0.84
- No Top-20 Longs PF: 0.48
- No Top-20 Shorts PF: 0.50
- No Both PF: 0.14

## Section 11 — Early/Late Split

**First Half** (113 trades)
- CAGR: -1.36%
- Max DD: 11.65%
- Win Rate: 39.82%

**Second Half** (113 trades)
- CAGR: -5.83%
- Max DD: 13.57%
- Win Rate: 39.82%

## Section 12 — Symbol Isolation Stress

| Removed | Remaining | CAGR | Max DD |
|---|---|---|---|
| AUDUSD | 191 | -2.57% | 15.36% |
| EURUSD | 181 | -2.71% | 12.75% |
| GBPUSD | 188 | -3.57% | 15.26% |
| NZDUSD | 186 | -2.88% | 12.91% |
| USDCAD | 190 | -4.40% | 14.57% |
| USDCHF | 194 | -3.36% | 13.06% |

## Section 13 — Per-Symbol PnL Breakdown

| Symbol | Trades | Net PnL | Win Rate | % Contribution |
|---|---|---|---|---|
| USDCAD | 36 | $98.84 | 36.1% | -12.1% |
| GBPUSD | 38 | $-70.13 | 44.7% | +8.6% |
| USDCHF | 32 | $-111.82 | 46.9% | +13.7% |
| NZDUSD | 40 | $-210.71 | 35.0% | +25.9% |
| EURUSD | 45 | $-246.59 | 44.4% | +30.3% |
| AUDUSD | 35 | $-274.27 | 31.4% | +33.7% |

## Section 14 — Block Bootstrap (100 runs)

- Mean CAGR: -15.23%
- Median CAGR: -15.20%
- 5th pctl CAGR: -23.43%
- 95th pctl CAGR: -7.93%
- Mean DD: 41.42%
- Worst DD: 66.24%
- Runs ending below start: 35

## Section 15 — Monthly Seasonality [MEDIUM MODE]

- SUPPRESSED: 226 trades < 300 threshold
- Dispersion: max deviation 54.65 from global mean -3.60

## Section 16 — Weekday Seasonality [MEDIUM MODE]

- SUPPRESSED: Not applicable for 1D timeframe
- Dispersion: max deviation 23.15 from global mean -3.60
