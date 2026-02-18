# IDX19 Drawdown Audit

**Date:** 2026-02-12  
**Subject:** Max Drawdown Calculation Clarification

---

## 1. Calculation Method
The reported Max Drawdown (**-$2,121.76**) is calculated using **Method (A): Cumulative Trade PnL**.

- **Formula:** `Running_Equity - Peak_Equity`
- **Initial Capital:** Assumed **$0** (tracks pure PnL accumulation)
- **Normalization:** None (absolute USD values)

## 2. Drawdown Anatomy
The large drawdown occurred because the strategy **gave back 100% of its accumulated profits** and briefly went negative before recovering.

| Metric | Value | Trade # |
|:---|---:|---:|
| **Peak Equity** | **+$1,955.24** | #940 |
| **Trough Equity** | **-$166.52** | #1063 |
| **Absolute Drop** | **$2,121.76** | |
| **% Retracement** | **108.5%** | |

> The strategy accumulated ~$1,955 in profit, then lost all of it plus ~$166 extra, before eventually rallying to finish at **$3,570**.

## 3. Conclusion
The figure is accurate. The large scale relative to final PnL reflects a **catastrophic mid-curve failure** where the strategy effectively "busted" its accumulated gains.
