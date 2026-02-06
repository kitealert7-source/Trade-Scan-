# Consolidate FX Structural Signal Report (2025)

**Objective:** Measure frequency and reliability of the "London Expansion → Overlap Pullback → Continuation" structure across the FX market (Majors + Crosses).
**Scope:** 11 FX Pairs (7 Majors + 4 Crosses).
**Data:** 15m RESEARCH datasets (OctaFX), Year 2025.
**Logic:** Frozen diagnostic scan (ATR Gate -> London Expansion -> Overlap Pullback -> Continuation).

## Executive Summary

| Metric | Total (11 Pairs) |
|:---|:---:|
| **Total Eligible Days** | 1,111 |
| **Total Expansions** | 281 |
| **Valid Pullbacks** | **11** |
| **Continuations** | **11** |
| **Overall Reliability** | **100.0%** |

*Key Insight:* The structure is **exceptionally rare** (avg 1 occurrence per pair per year) but appears **perfectly reliable** (11/11) in the 2025 sample when strict criteria are met.

---

## Detailed Results by Pair

### Major Pairs (7)
| Pair | Eligible | Expansions | Pullbacks | Continuations | Reliability |
|:---|:---:|:---:|:---:|:---:|:---:|
| **EURUSD** | 101 | 22 | 1 | 1 | 100.0% |
| **GBPUSD** | 101 | 33 | 1 | 1 | 100.0% |
| **USDJPY** | 101 | 24 | 0 | 0 | - |
| **USDCHF** | 101 | 33 | 1 | 1 | 100.0% |
| **AUDUSD** | 101 | 30 | 2 | 2 | 100.0% |
| **NZDUSD** | 101 | 27 | 1 | 1 | 100.0% |
| **USDCAD** | 101 | 21 | 0 | 0 | - |
| **Subtotal** | **707** | **190** | **6** | **6** | **100.0%** |

### Cross Pairs (4)
| Pair | Eligible | Expansions | Pullbacks | Continuations | Reliability |
|:---|:---:|:---:|:---:|:---:|:---:|
| **GBPAUD** | 101 | 22 | 3 | 3 | 100.0% |
| **GBPNZD** | 101 | 27 | 0 | 0 | - |
| **AUDNZD** | 101 | 20 | 1 | 1 | 100.0% |
| **EURAUD** | 101 | 22 | 1 | 1 | 100.0% |
| **Subtotal** | **404** | **91** | **5** | **5** | **100.0%** |

---

## Technical Notes
- **Eligibility:** Days were filtered by Median ATR (40-80th percentile) to exclude low volatility and extreme outlier days.
- **Expansion Logic:** London Range (08:00-09:30 UTC) >= 1.2x Rolling Median (20 days).
- **Pullback Definition:** 30-50% retracement of expansion move, occurring within the London-NY Overlap (13:00-16:00 UTC), without crossing the move's midpoint.
- **Null Results:** Pairs with 0 pullbacks indicate no valid structural setup occurred in the eligible 2025 sample.
