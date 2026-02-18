# IDX21 vs IDX19 Comparison

**Report Date:** 2026-02-12
**Status:** Post-Execution Analysis

| Feature | IDX19 | IDX20 | IDX21 |
|:---|:---|:---|:---|
| Strategy | Base (Dip Buy) | Base + Trend Filter | Base + **Shock Cooldown** |
| Vol Filter | ≤75 | ≤75 | ≤75 |
| Condition | - | Close > EMA(200) | **Pause 15 bars after >75 spike** |

---

## Head-to-Head Metrics

| Metric | IDX19 (Base) | IDX20 (Trend) | IDX21 (Cooldown) | Diff (21 vs 19) |
| :--- | ---: | ---: | ---: | :---: |
| **Net PnL** | **$3,570** | $1,840 | **$2,236** | **-$1,334** |
| **PnL Retention** | 100% | 51% | **63%** | -37% |

### Symbol-Level Breakdown (IDX21)
| Symbol | PnL | vs IDX19 |
|:---|---:|---:|
| **NAS100** | **$1,183** | +$66 |
| **JPN225** | **$1,041** | +$238 |
| **US30** | $676 | -$66 |
| **AUS200** | $231 | -$53 |
| **UK100** | $207 | -$40 |
| **SPX500** | $187 | -$37 |
| **EUSTX50** | $82 | -$64 |
| **ESP35** | -$37 | -$232 |
| **FRA40** | -$115 | -$160 |
| **GER40** | -$218 | +$15 |

---

## Verdict
**IDX21 (Volatility Shock Cooldown) creates a "middle ground" but still underperforms.**

1.  **Partial Recovery:** IDX21 recovered ~$400 compared to the disastrous IDX20 Trend Filter.
2.  **Specific Wins:** It actually **outperformed IDX19 on NAS100 (+$66) and JPN225 (+$238)**.
    -   This suggests the cooldown effectively dodged some "falling knife" entries in high-beta tech/growth indices.
3.  **Broad Drag:** For European indices (ESP35, FRA40), the cooldown caused significant underperformance, likely missing the "V-shape" recovery bounces that follow volatility spikes.

**Conclusion:** The **15-bar cooldown is too blunt**. It helps in JPN225/NAS100 but hurts everywhere else.
**Recommendation:** Refine cooldown to specific assets or reduce duration (e.g., 5 bars instead of 15).
