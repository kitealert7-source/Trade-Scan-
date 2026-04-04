# DYNAMIC PIP VALUE FEASIBILITY ANALYSIS

> **OUTCOME (2026-04-03):** This analysis recommended Option C (dynamic conversion). That approach was **not implemented**. Instead, MT5-verified static valuation was adopted: `usd_per_pu_per_lot = tick_value / tick_size` extracted directly from MT5 `symbol_info()` for all 31 symbols. This eliminates the YAML calibration anomalies identified below (AUDNZD, GBPAUD, EURGBP, JPN225, SPX500) without runtime FX rate dependencies. Frozen rate drift (~5-12% on non-USD symbols) is accepted. See `CAPITAL_SIZING_AUDIT.md` Sections 1 and 8 for the implemented design and `CAPITAL_WRAPPER_SAFETY_AUDIT.md` Section 9 for migration details.

---

## SECTION 1 — Required Data

### Traded Symbols — RESEARCH Data Availability

| Symbol | RESEARCH Data | Status |
| :--- | :--- | :--- |
| EURUSD | ✓ EURUSD_OCTAFX_MASTER | Available |
| GBPUSD | ✓ GBPUSD_OCTAFX_MASTER | Available |
| USDJPY | ✓ USDJPY_OCTAFX_MASTER | Available |
| USDCAD | ✓ USDCAD_OCTAFX_MASTER | Available |
| USDCHF | ✓ USDCHF_OCTAFX_MASTER | Available |
| AUDUSD | ✓ AUDUSD_OCTAFX_MASTER | Available |
| NZDUSD | ✓ NZDUSD_OCTAFX_MASTER | Available |
| EURJPY | ✓ EURJPY_OCTAFX_MASTER | Available |
| EURGBP | ✓ EURGBP_OCTAFX_MASTER | Available |
| EURAUD | ✓ EURAUD_OCTAFX_MASTER | Available |
| GBPJPY | ✓ GBPJPY_OCTAFX_MASTER | Available |
| GBPAUD | ✓ GBPAUD_OCTAFX_MASTER | Available |
| GBPNZD | ✓ GBPNZD_OCTAFX_MASTER | Available |
| AUDNZD | ✓ AUDNZD_OCTAFX_MASTER | Available |
| AUDJPY | ✓ AUDJPY_OCTAFX_MASTER | Available |
| CADJPY | ✓ CADJPY_OCTAFX_MASTER | Available |
| CHFJPY | ✓ CHFJPY_OCTAFX_MASTER | Available |
| NZDJPY | ✓ NZDJPY_OCTAFX_MASTER | Available |

### USD Conversion Pairs Required

For dynamic pip value, the wrapper needs the USD exchange rate for the **quote currency** of each traded pair at entry time.

| Quote Currency | Conversion Pair | Available in RESEARCH? |
| :--- | :--- | :--- |
| USD | (none needed) | N/A — pairs like EURUSD, GBPUSD are already USD-denominated |
| JPY | USDJPY | ✓ Available |
| CAD | USDCAD | ✓ Available |
| CHF | USDCHF | ✓ Available |
| GBP | GBPUSD (invert) | ✓ Available |
| AUD | AUDUSD (invert) | ✓ Available |
| NZD | NZDUSD (invert) | ✓ Available |

**Verdict: All conversion pairs are available in RESEARCH data.**

---

## SECTION 2 — Implementation Complexity

### Option A: Dynamic Conversion Using RESEARCH Data

| Step | Description | Complexity |
| :--- | :--- | :--- |
| Pre-load conversion pair daily close series | Load 7 daily RESEARCH CSVs at wrapper init | LOW |
| Build lookup: `(quote_ccy, date) → USD_rate` | Dictionary from daily close prices | LOW |
| At each ENTRY event, look up `USD_rate` for entry date | Simple dict lookup (or bisect for nearest date) | LOW |
| Compute: `usd_per_price_unit_per_lot = contract_size × USD_rate` | One multiplication | LOW |

**Overall: LOW complexity.** 7 daily CSV loads + dict construction at init. O(1) lookup per event.

### Option B: Fallback to Static for USD-Quote Pairs

USD-quote pairs (EURUSD, GBPUSD, AUDUSD, NZDUSD) have `USD_rate = 1.0` exactly. No lookup needed.

**Complexity: TRIVIAL** — hardcode `USD_rate = 1.0` for quote_ccy == USD.

### Option C: Handling Missing Conversion Pairs

All 7 required conversion pairs exist. If a future symbol has no conversion pair:

- Fall back to static YAML calibration
- Log warning

**Complexity: LOW.**

### Combined Classification: **LOW**

---

## SECTION 3 — Performance Impact

### Does wrapper need bar-level replay?

**NO.** The wrapper processes ENTRY and EXIT events only. It needs the USD conversion rate at **one point per trade** (entry timestamp). This is a single daily-close lookup, not a bar-by-bar replay.

| Requirement | Answer |
| :--- | :--- |
| Bar-level replay? | NO |
| Entry price lookup only? | YES — one lookup per ENTRY event |
| Data granularity needed | Daily close is sufficient (trade sizing happens once at entry) |
| Memory overhead | ~7 daily series × ~6000 bars (19yr) = ~42,000 rows total. Negligible. |
| Lookup cost | O(1) dict or O(log n) bisect per entry. Negligible. |

---

## SECTION 4 — Migration Risk

### Would dynamic conversion affect historical alpha comparison?

**YES, but appropriately.** The static calibration uses a single-point-in-time conversion rate. Dynamic conversion uses the rate at each trade's entry date. This means:

- Lot sizes change per trade (especially for USDJPY where rate moved 110→155)
- PnL in USD changes proportionally
- This is **more accurate**, not distorted

### Would acceptance sets change materially?

**YES for non-USD-quote pairs.** Changed lot sizes → changed notional → different leverage cap hits → different acceptance/rejection sets. This is **desired** — the current acceptance sets for cross pairs are based on incorrect calibration (see AUDNZD anomaly).

For USD-quote pairs: **NO change** (rate = 1.0, same as static).

### Would it break determinism?

**NO.** RESEARCH daily close data is static historical data. Same input → same lookup → same output. Fully deterministic.

---

## SECTION 5 — RECOMMENDATION

### Option B: Fix Anomalous YAML + Keep Static

| Pro | Con |
| :--- | :--- |
| Zero code change to wrapper | Still drifts over 19yr for non-USD-quote |
| Quick fix | Requires manual recalibration of 7+ YAMLs |
| | Calibration point ambiguity remains |

### Option C: Implement Dynamic Conversion

| Pro | Con |
| :--- | :--- |
| Correct by construction — no calibration drift | Requires loading 7 extra daily CSVs |
| Eliminates AUDNZD/GBPAUD anomalies permanently | Changes acceptance sets for non-USD pairs |
| No manual YAML maintenance | Slightly more complex init |
| Works automatically for any future symbol | |

### Recommendation: **Option C — Implement Dynamic Conversion**

**Justification:**

1. All required conversion pair data is already available in RESEARCH layer.
2. Implementation complexity is LOW (daily close lookup, not bar replay).
3. Performance impact is negligible (42k rows total, O(1) lookup per event).
4. Eliminates both the AUDNZD/GBPAUD anomalies AND the systematic 19-year drift for all non-USD-quote pairs in a single structural fix.
5. Determinism is preserved.
6. Static YAML calibration can remain as a fallback for missing conversion pairs.
7. USD-quote pairs are unaffected (rate = 1.0 always).

The wrapper was designed to simulate realistic deployable capital. Using the actual conversion rate at entry time is not an optimization — it is a correctness requirement.

---

## SECTION 6 — ACTUAL OUTCOME (2026-04-03)

### What Was Implemented Instead

**Option D: MT5 Static Valuation (not considered in original analysis)**

Rather than implementing dynamic conversion from RESEARCH daily close data (Option C), the system now extracts `tick_value` and `tick_size` directly from MT5 `symbol_info()` at a fixed point in time and stores them in broker spec YAMLs.

| Dimension | Option C (proposed) | Option D (implemented) |
|-----------|-------------------|----------------------|
| Source | RESEARCH daily close CSVs | MT5 `symbol_info()` extraction |
| Rate freshness | Per-trade (entry date) | Frozen at extraction date |
| Runtime dependency | 7 daily CSV series | None (YAML lookup) |
| Code complexity | Moderate (bisect lookup) | Minimal (dict read) |
| Drift | None | ~5-12% on non-USD over 2yr |
| Correctness | Exact | Bounded approximation |

### Why Option C Was Not Chosen

1. **MT5 tick_value is authoritative.** It is the value the broker uses for margin and PnL computation. Deriving conversion rates from RESEARCH close prices introduces a secondary data source that may disagree with the broker's own valuation.

2. **Static is simpler and sufficient.** The bounded drift (~5-12% on JPY over 2 years) affects risk sizing by a proportional amount. For $50 fixed risk, this means $47-$56 effective risk — within tolerance for research.

3. **No runtime dependencies.** Static valuation requires no conversion pair data availability, no bisect lookups, no missing-pair fallback logic.

4. **The anomalies this analysis identified are fixed.** JPN225 (16x overestimate), SPX500 (10x), EURGBP (1057x underestimate), USDCAD (99x underestimate) — all corrected by MT5 extraction, not by dynamic conversion.

### Status
This document is retained as a historical feasibility study. The recommendation (Option C) is superseded by the MT5 static approach. The analysis of required data, complexity, and performance impact remains valid reference material for any future reconsideration of dynamic conversion.
