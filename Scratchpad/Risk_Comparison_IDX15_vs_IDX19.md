# IDX15 vs IDX19 Comparison

**Report Date:** 2026-02-12

| Feature | IDX15 | IDX19 |
|:---|:---|:---|
| Vol Filter | ≤75 | ≤75 |
| Time Exit | 5 bars | 5 bars |
| Stop Loss | **None** | **2 × ATR(14) fixed** |

---

## Head-to-Head Metrics

| Metric | IDX15 | IDX19 | Δ |
| :--- | ---: | ---: | :---: |
| **Net PnL** | $3,570.15 | $3,570.15 | **0** |
| **Trade Count** | 1,797 | 1,797 | 0 |
| **Win Rate** | 58% | 58% | 0 |
| **Profit Factor** | 1.25 | 1.25 | 0 |
| **Max DD %** | 6.0% | 6.0% | 0 |
| **Max DD USD** | $313.67 | $313.67 | 0 |
| **Return/DD** | 1.46 | 1.46 | 0 |
| **Sharpe** | 1.17 | 1.17 | 0 |
| **Sortino** | 1.01 | 1.01 | 0 |
| **K-Ratio** | 9.08 | 9.08 | 0 |
| **SQN** | 1.05 | 1.05 | 0 |

---

## Volatility Bucket Breakdown

| Regime | IDX15 | IDX19 |
|:---|---:|---:|
| **Low Vol PnL** | $3,396 | $3,396 |
| **Normal Vol PnL** | $4,150 | $4,150 |
| **High Vol PnL** | -$3,976 | -$3,976 |

---

## Per-Symbol Comparison

| Symbol | IDX15 PnL | IDX19 PnL | Trades |
|:---|---:|---:|---:|
| NAS100 | $1,116 | $1,116 | 155 |
| JPN225 | $803 | $803 | 199 |
| US30 | $742 | $742 | 177 |
| AUS200 | $284 | $284 | 201 |
| UK100 | $248 | $248 | 203 |
| SPX500 | $224 | $224 | 173 |
| ESP35 | $195 | $195 | 218 |
| EUSTX50 | $146 | $146 | 196 |
| FRA40 | $45 | $45 | 210 |
| GER40 | -$233 | -$233 | 65 |

---

## Key Finding

> [!IMPORTANT]
> **IDX15 and IDX19 produce 100% identical results.** The 2×ATR(14) fixed stop loss was **never triggered** across all 1,797 trades and 10 symbols over 11 years of data.

### Why the stop never fired:
1. **Stop is too wide:** 2×ATR(14) below entry is a large cushion — most mean-reversion dip buys recover before falling that far
2. **Time exit catches losers first:** The 5-bar time exit forces exits on stagnant trades before they can reach the stop level
3. **Price exit catches winners:** Winning trades exit via Close > HH_prev well before any stop concern

### Conclusion:
The 2×ATR stop loss adds **zero protective value** to this strategy. The time exit (5 bars) already serves as the effective risk management mechanism.

### Next Steps:
To make a stop loss impactful, consider:
- **Tighter stop:** 1×ATR or 0.5×ATR  
- **Trailing stop:** Move stop up as trade progresses
- **Longer time exit:** Allow more bars so the stop has a chance to trigger before time exits
