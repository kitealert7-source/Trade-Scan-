# IDX19 vs IDX20 Comparison

**Report Date:** 2026-02-12
**Status:** Post-Cleanup Re-Run

| Feature | IDX19 | IDX20 |
|:---|:---|:---|
| Strategy | Base + 2×ATR Stop | Base + **EMA(200) Trend Filter** |
| Vol Filter | ≤75 | ≤75 |
| Condition | - | **Close > EMA(200)** |

---

## Head-to-Head Metrics

| Metric | IDX19 | IDX20 | Diff |
| :--- | ---: | ---: | :---: |
| **Net PnL** | **$3,570.15** | $1,840.38 | **-$1,729.77** |
| **Trade Count** | 1,797 | 1,355 | -442 |
| **Win Rate** | 58% | 58% | 0% |
| **Profit Factor** | 1.25 | **1.26** | +0.01 |
| **Max DD %** | 6.0% | **4.0%** | -2.0% |
| **Sharpe** | **1.17** | 0.94 | -0.23 |
| **Analysis** | **Robust Base** | **Over-Filtered** | |

---

## Verdict
**IDX19 (Base Strategy) outperforms IDX20 (Trend Filter) significantly.**
-   **PnL Impact:** The EMA(200) filter slashed profits by ~48%.
-   **Missed Trades:** 442 trades were filtered out, many of which were profitable shallow dips below the 200 EMA.
-   **Risk/Reward:** The slight reduction in Max DD (2%) does not justify the massive loss in profitability.

**Recommendation:** Discard the trend filter. Stick with the base logic (IDX19/IDX15).
