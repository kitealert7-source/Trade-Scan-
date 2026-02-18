# IDX22 vs IDX24 vs IDX25 — Portfolio Comparison

## Strategy Lineage

| | IDX22 (Baseline) | IDX24 (Vol-Weighted) | IDX25 (Pruned) |
|---|---|---|---|
| **Sizing** | 1× uniform | 2× at ATR pct ≤ 40, 1× at 40–75 | Same as IDX24 |
| **Symbols** | 10 (full basket) | 10 (full basket) | 7 (removed GER40, FRA40, UK100) |
| **Capital** | $50,000 (10 × $5k) | $50,000 | $35,000 (7 × $5k) |

## Key Metrics Comparison

| Metric | IDX22 | IDX24 | IDX25 |
|--------|-------|-------|-------|
| **Net PnL** | $3,722 | $4,942 | **$5,220** |
| **CAGR** | 0.75% | 0.98% | **1.45%** |
| **Sharpe** | 0.97 | 0.79 | **0.98** |
| **Sortino** | 0.99 | 0.81 | **0.99** |
| **Max DD (%)** | **-3.92%** | -6.43% | -7.80% |
| **Max DD (USD)** | **-$2,034** | -$3,405 | -$2,940 |
| **Return/DD** | **1.83** | 1.45 | 1.78 |
| **K-Ratio** | **30.49** | 22.27 | 27.36 |
| **MAR** | **0.19** | 0.15 | **0.19** |
| **Avg Correlation** | 0.219 | 0.220 | 0.239 |
| **Top Contributor %** | **30.5%** | 44.7% | 42.4% |
| **Trades** | 1,737 | 1,737 | 1,282 |
| **Recommendation** | HOLD | HOLD | HOLD |

## Regime Performance

| Regime | IDX22 PnL | IDX24 PnL | IDX25 PnL |
|--------|----------|----------|----------|
| **Low vol** | $3,352 | $5,741 | **$4,751** |
| **Normal vol** | $4,052 | $6,328 | **$5,743** |
| **High vol** | -$3,682 | **-$7,128** | -$5,273 |

## Stress Tests

| Scenario | IDX22 | IDX24 | IDX25 |
|----------|-------|-------|-------|
| Baseline PnL | $3,722 | $4,942 | $5,220 |
| Remove top (NAS100) | $2,586 | $2,731 | $3,009 |
| Remove worst | $3,933 | $5,312 | $5,007 |
| Remove US cluster | $1,599 | $1,169 | $1,448 |
| **US survival %** | 43% | 24% | **28%** |

## Analysis

### IDX25 (Pruned Basket) is the Best Overall Strategy

1. **Highest PnL** ($5,220) with lowest allocated capital ($35,000 vs $50,000)
2. **Best CAGR** (1.45%) — nearly 2× IDX22 and 1.5× IDX24
3. **Restored Sharpe** (0.98) — nearly matching IDX22's 0.97 while producing +40% more PnL
4. **Better capital efficiency**: Same PnL with 30% less capital deployed
5. **MAR ratio restored** to 0.19 (matching IDX22 baseline)

### Tradeoffs

- MaxDD % deepened (-7.80% vs IDX22's -3.92%) — the 2× sizing amplifies drawdowns
- NAS100 concentration remains high (42.4%) — structural risk unchanged
- High-vol regime losses still significant (-$5,273)

### Why Pruning Helped

Removed symbols contributed negative or near-zero edge:
- **GER40**: -$370 PnL, PF 0.78 (only ~4 years of data)
- **FRA40**: -$1 PnL, PF 1.00 (dead weight, consumed capital)
- **UK100**: +$93 PnL, PF 1.06 (marginal edge, not worth the capital allocation)

Removing these freed capital for higher-conviction bets and eliminated noise from the portfolio.

## Snapshot Locations

| Strategy | Path |
|----------|------|
| IDX22 | [portfolio_evaluation](file:///c:/Users/faraw/Documents/Trade_Scan/strategies/IDX22/portfolio_evaluation) |
| IDX24 | [portfolio_evaluation](file:///c:/Users/faraw/Documents/Trade_Scan/strategies/IDX24/portfolio_evaluation) |
| IDX25 | [portfolio_evaluation](file:///c:/Users/faraw/Documents/Trade_Scan/strategies/IDX25/portfolio_evaluation) |
