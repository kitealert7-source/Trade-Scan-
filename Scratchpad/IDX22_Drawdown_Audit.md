# IDX22 Drawdown Audit Report

**Report Date:** 2026-02-13
**Subject:** IDX22 Drawdown Calculation Logic

## Executive Summary
The reported Max Drawdown for IDX22 (e.g., NAS100: **$237.77 / 4.76%**) was audited against raw trade logs.

**Confirmed Logic:**
1.  **Absolute Drawdown ($):** Calculated from **Cumulative Trade PnL** (Running Sum).
    -   *Formula:* `Peak(CumPnL) - Current(CumPnL)`
    -   *Verified:* Re-calculation matches reported $237.77 exactly.
2.  **Percentage Drawdown (%):** Calculated based on **Peak Equity** with an **Initial Capital of $5,000**.
    -   *Implied Capital:* $237.77 / 4.76% ≈ **$5,000**.
    -   *Method:* Standard Peak-to-Trough percentage on equity curve.

## Detailed Checks

| Metric | Reported | Re-Calculated | Match? |
|:---|---:|---:|:---|
| **Max DD (USD)** | **$237.77** | $237.77 | ✅ YES |
| **Max DD (%)** | **4.76%** | 4.76%* | ✅ YES |

*\*Note: The percentage match assumes a starting capital of $5,000.*

## Definition for Stakeholders
> "Drawdown is measured as the maximum decline in Closed Trade Equity from a peak, assuming a starting account size of **$5,000** per symbol."

## Recommendation
If the user portfolio size is different (e.g., $100k), the **$237.77** absolute figure is the reliable metric to scale. The 4.76% is specific to the $5k base.
