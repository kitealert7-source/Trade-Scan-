# IDX22 vs IDX21 vs IDX19 Comparison

**Report Date:** 2026-02-13
**Status:** Post-Execution Analysis

| Feature | IDX19 | IDX21 | IDX22 |
|:---|:---|:---|:---|
| Strategy | Base (Dip Buy) | Base + Shock Cooldown | Base + **Short Cooldown** |
| Vol Filter | ≤75 | ≤75 | ≤75 |
| Cooldown | - | 15 Bars | **5 Bars** |

---

## Head-to-Head Metrics

| Metric | IDX19 (Base) | IDX21 (15-bar) | IDX22 (5-bar) | Diff (22 vs 19) |
| :--- | ---: | ---: | ---: | :---: |
| **Net PnL** | **$3,570** | $2,236 | **$3,293** | **-$277** |
| **PnL Retention** | 100% | 63% | **92%** | -8% |
| **Trade Count** | 1,797 | ~1,500 | ~1,680 | -117 |

### Symbol-Level Breakdown (IDX22)
| Symbol | PnL | vs IDX19 | vs IDX21 |
|:---|---:|---:|---:|
| **NAS100** | **$1,136** | +$20 | -$46 |
| **JPN225** | **$976** | +$173 | -$65 |
| **US30** | $748 | +$6 | +$72 |
| **AUS200** | $269 | -$15 | +$38 |
| **SPX500** | $240 | +$16 | +$53 |
| **ESP35** | $181 | -$14 | +$218 |
| **UK100** | $175 | -$73 | -$32 |
| **EUSTX50** | $168 | +$22 | +$86 |
| **FRA40** | $41 | -$4 | +$156 |
| **GER40** | -$211 | +$12 | +$6 |

---

## Verdict
**IDX22 (5-bar Cooldown) is the "Goldilocks" solution.**

1.  **Retention:** It retains **92% of the Base Strategy profit** ($3,293 vs $3,570), compared to only 63% for IDX21.
2.  **Risk Mitigation:** It still provides protection in high-volatility events (JPN225 +$173 over base).
3.  **Recovery:** Unlike IDX21, it does **not** miss the V-shape recovery in European indices (ESP35/FRA40 recovered significantly vs IDX21).

**Recommendation:** IDX22 is a strong contender to replace the Base Strategy if risk mitigation is prioritized over pure profit maximization. The cost is small ($277 over 11 years) for potential crash protection.
