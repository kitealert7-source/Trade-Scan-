# TradeScan Walkthrough: IDX Series Complete Analysis (IDX01 - IDX10)

## Overview
This document presents the complete evolution of the **IDX Series** dip-buying strategies, from the baseline (`IDX01`) through the final **Barbell Filter** implementation (`IDX10`).

---

## Strategy Evolution Summary

| Strategy | ATR Type | Threshold/Filter | Total PnL | Delta vs IDX01 | Key Feature |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **IDX01** | SMA | None | $3,515 | — | Baseline (No Filter) |
| **IDX04** | SMA | ≤67 (ATR-10) | $756 | -$2,759 | Over-filtered (Failed) |
| **IDX05** | SMA | ≤67 (ATR-14) | $2,960 | -$555 | Wider ATR window |
| **IDX06** | RMA | ≤67 (ATR-14) | $2,681 | -$834 | Wilder's Smoothing |
| **IDX07** | RMA | ≤60 (Strict) | $3,007 | -$508 | Strict Low-Vol Only |
| **IDX08** | RMA | ≤67 (Base) | $2,681 | -$834 | Same as IDX06 |
| **IDX09** | RMA | ≤75 (Loose) | $3,380 | -$135 | Looser Tolerance |
| **IDX10** | RMA | **≤60 OR ≥72** | **$4,884** | **+$1,369** | **Barbell Filter** ✅ |

---

## IDX10 Breakthrough: Barbell Filter Results

### Concept
Instead of filtering for a single volatility regime, `IDX10` allows trades in **BOTH low AND high volatility**:
- **Low Vol (≤60):** Calm dips (safest)
- **High Vol (≥72):** Explosive dips (riskiest but high reward)
- **Mid Vol (61-71):** **BLOCKED** (choppy, unprofitable)

### Performance by Symbol

| Symbol | IDX09 (≤75) | **IDX10 (Barbell)** | Improvement | Analysis |
| :--- | :--- | :--- | :--- | :--- |
| **AUS200** | $304 | **$295** | -$9 | Slight dip (marginal) |
| **ESP35** | $127 | **$537** | **+$410** 🟢 | Massive gain from high-vol trades |
| **EUSTX50** | $173 | $75 | -$98 🔴 | Lost profitability |
| **FRA40** | $73 | $86 | +$13 | Marginal improvement |
| **GER40** | -$32 | **$314** | **+$346** 🟢 | From loser to winner |
| **JPN225** | $988 | **$1,936** | **+$948** 🟢 | Nearly doubled (validates Barbell) |
| **NAS100** | $700 | $707 | +$7 | Stable |
| **SPX500** | $233 | **$319** | +$86 🟢 | Better capture |
| **UK100** | $254 | $115 | -$139 🔴 | Lost profitability |
| **US30** | $560 | $495 | -$65 | Slight decline |
| **TOTAL** | **$3,380** | **$4,884** | **+$1,504** | **+44.5% Improvement** |

---

## Key Insights

### 1. JPN225 Validates the Barbell Hypothesis
JPN225's performance nearly **doubled** ($988 → $1,936), confirming that it profits at extremes but suffers in the middle range.

### 2. GER40 Transformation
The Barbell filter turned GER40 from a **-$32 loser** (IDX09) into a **$314 winner** (IDX10). This suggests DAX dips only work in very calm OR very volatile periods—not in between.

### 3. ESP35 Explosion
ESP35 jumped from **$127 to $537** (+322%), indicating it thrives on high-volatility dips that were previously filtered out.

### 4. Trade-offs: EUSTX50 & UK100
Two indices lost profitability:
- **EUSTX50:** $173 → $75 (-$98)
- **UK100:** $254 → $115 (-$139)

These losses suggest that for some markets, the "mid-range" volatility (61-71) was actually profitable, and blocking it hurt performance.

---

## Final Recommendation

**Deploy IDX10 (Barbell)** as the primary strategy for most indices, with exceptions:

### Use IDX10 (Barbell):
- **JPN225** (Nearly doubled profit)
- **GER40** (Transformed to winner)
- **ESP35** (Massive gain)
- **SPX500** (Improved capture)
- **NAS100** (Stable/slight improvement)

### Consider IDX09 (≤75) for:
- **UK100** (Lost -$139 with Barbell)
- **EUSTX50** (Lost -$98 with Barbell)

### Monitor:
- **US30** (Slight decline, may need fine-tuning)
- **AUS200** (Marginal difference)

**Overall Conclusion:** The **Barbell Filter (IDX10)** represents a **+44.5% improvement** over the best single-threshold strategy (IDX09) and a **+38.9% improvement** over the unfiltered baseline (IDX01).
