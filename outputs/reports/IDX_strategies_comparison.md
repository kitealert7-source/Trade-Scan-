# Portfolio Strategy Comparison — IDX22 / IDX24 / IDX25 / IDX26

## Strategy Lineage

| | **IDX22 (Baseline)** | **IDX24 (Vol-Sized)** | **IDX25 (Aggressive)** | **IDX26 (Quality)** |
|---|---|---|---|---|
| **Sizing** | 1× uniform | 2× low-vol | 2× low-vol | **1× uniform** |
| **Basket** | Full (10) | Full (10) | Pruned (7) | **Pruned (7)** |
| **Capital** | $50,000 | $50,000 | $35,000 | **$35,000** |

*Pruned Basket: Removed GER40, FRA40, UK100 (low/negative edge).*

## Executive Summary

| Metric | IDX22 | IDX24 | IDX25 | IDX26 |
|--------|-------|-------|-------|-------|
| **Net PnL** | $3,722 | $4,942 | **$5,220** | $3,717 |
| **CAGR** | 0.75% | 0.98% | **1.45%** | 1.05% |
| **Sharpe** | 0.97 | 0.79 | 0.98 | **1.14** |
| **Sortino** | 0.99 | 0.81 | 0.99 | **1.14** |
| **Max DD (%)** | -3.92% | -6.43% | -7.80% | **-4.99%** |
| **Return/DD** | 1.83 | 1.45 | 1.78 | **2.03** |
| **K-Ratio** | 30.49 | 22.27 | 27.36 | **31.30** |
| **Rating** | HOLD | HOLD | HOLD | **PROMOTE** |

## Key Findings

### 1. Pruning Works (IDX22 → IDX26)
Removing the 3 weak symbols (GER40/FRA40/UK100) while keeping 1× sizing:
- **Sharpe Ratio** improved from 0.97 → **1.14**.
- **Return/DD** improved from 1.83 → **2.03**.
- **Capital Efficiency**: Generated the **same PnL** ($3,717 vs $3,722) using **30% less capital**.

### 2. Volatility Sizing adds Profit but Risk (IDX26 → IDX25)
Moving from 1× (IDX26) to 2× vol-weighted (IDX25) on the pruned basket:
- **Profit**: Increased +40% ($3,717 → $5,220).
- **Risk**: Max Drawdown deepened significantly (-4.99% → -7.80%).
- **Quality**: Sharpe Ratio dropped (1.14 → 0.98).

### 3. Structural Comparison

- **Highest Quality**: **IDX26**. It has the smoothest equity curve (K-Ratio 31.3), best risk-adjusted returns, and passes the "Promote" threshold.
- **Highest Return**: **IDX25**. Best for aggressive growth if the larger drawdown is acceptable.
- **Worst Performer**: **IDX24**. 2× sizing on bad assets (GER40) amplified losses.

## Recommendation

**Promote IDX26.**
The pruned basket with uniform sizing offers the most robust, high-quality core strategy. If higher returns are desired later, leverage should be applied at the portfolio level *after* this robust core is established, rather than embedding 2× sizing into the strategy logic itself.
