# USDCHF ISOLATION ANALYSIS — AK36_FX_PORTABILITY_4H / CONSERVATIVE_V1

Generated: 2026-02-25 13:06:37

Symbol: **USDCHF** only | Deployable trades: **856**

## 1. Fixed-Lot Stats (Raw Stage-1)

- Trades: 1222
- PF: 1.15
- Net PnL: $600.69
- Win Rate: 40.8%

### Year-Wise PnL (Fixed-Lot)

| Year | Trades | Net PnL | Win Rate |
|---|---|---|---|
| 2007 | 52 | $-26.24 | 34.6% |
| 2008 | 64 | $246.63 | 50.0% |
| 2009 | 65 | $-91.84 | 35.4% |
| 2010 | 59 | $38.83 | 42.4% |
| 2011 | 72 | $254.27 | 45.8% |
| 2012 | 67 | $-130.21 | 31.3% |
| 2013 | 57 | $51.47 | 52.6% |
| 2014 | 65 | $-28.03 | 43.1% |
| 2015 | 73 | $172.27 | 35.6% |
| 2016 | 63 | $-71.86 | 34.9% |
| 2017 | 61 | $-30.01 | 39.3% |
| 2018 | 68 | $-5.48 | 36.8% |
| 2019 | 64 | $26.61 | 50.0% |
| 2020 | 59 | $80.78 | 37.3% |
| 2021 | 65 | $10.19 | 41.5% |
| 2022 | 66 | $86.60 | 43.9% |
| 2023 | 67 | $-18.48 | 41.8% |
| 2024 | 69 | $11.02 | 40.6% |
| 2025 | 62 | $-7.73 | 37.1% |
| 2026 | 4 | $31.90 | 50.0% |

### Rolling 1Y (Fixed-Lot)

- Total daily rolling windows: 6532
- Negative windows: 2267 (34.7%)
- Worst 1Y PnL: $-175.53
- Best 1Y PnL: $324.13
- Mean 1Y PnL: $33.25

### Regime Breakdown (Fixed-Lot)

**Volatility Regime:**

| Regime | Trades | Net PnL | PF |
|---|---|---|---|
| high | 444 | $427.97 | 1.27 |
| low | 464 | $-65.21 | 0.96 |
| normal | 314 | $237.93 | 1.26 |

**Trend Regime:**

| Regime | Trades | Net PnL | PF |
|---|---|---|---|
| neutral | 353 | $64.18 | 1.05 |
| strong_down | 246 | $475.96 | 1.67 |
| strong_up | 45 | $13.65 | 1.11 |
| weak_down | 358 | $-99.58 | 0.92 |
| weak_up | 220 | $146.48 | 1.17 |

## 2. Deployable Stats (Position-Sized)

- CAGR: 2.47%
- Final Equity: $15,832.99
- Max DD: 12.45%
- Recovery Factor: 4.69

### Rolling 1Y DD (Deployable)

- Worst rolling 1Y DD: 12.45%
- Mean rolling 1Y DD: 3.72%
- Negative 1Y return windows: 2256

## 3. Tail Contribution

- Top 1 trade: 15.28%
- Top 5 trades: 62.48%
- Top 1% (8): 86.85%
- Total PnL: $5,832.99

## 4. Friction Stress Test

| Scenario | Net Profit | PF | Degradation |
|---|---|---|---|
| Baseline | $5,832.99 | 1.16 | 0.00% |
| Slip 1.0 pip RT | $4,592.39 | 1.12 | 21.27% |
| Spread +50% | $4,902.54 | 1.13 | 15.95% |
| Severe (1.0 + 75%) | $3,196.72 | 1.08 | 45.20% |

## 5. Block Bootstrap (100 runs)

*Note: Block bootstrap resamples the full portfolio. Using Sequence MC on USDCHF trades instead.*

- Mean CAGR: 0.02%
- 5th pctl CAGR: 0.02%
- Mean DD: 19.18%
- Worst DD: 38.56%
- Runs below start capital: 0 / 100 (0%)

## 6. Diagnostic Summary

| Test | Result | Pass |
|---|---|---|
| Fixed-lot PF > 1.1 | 1.15 | ✅ |
| Survives friction (Severe PF > 1.0) | 1.08 | ✅ |
| Bootstrap 5th pctl CAGR > 0 | 0.02% | ✅ |
| Rolling 1Y not structurally negative | 34.7% negative | ✅ |

**CONCLUSION: USDCHF shows a potentially CHF-specific breakout edge. Further OOS testing warranted.**