# Seasonality Diagnostics — Structural Integration Proposal

## 1. Problem Statement

The current robustness report (14 sections) evaluates edge persistence across Monte Carlo resampling, friction, drawdown anatomy, directional bias, and bootstrap — but has **no temporal segmentation by calendar period**. This proposal evaluates whether adding Month / Quarter / Weekday breakdowns would produce actionable signal or just noise.

---

## 2. Current Section Inventory (14 sections)

| # | Section | Signal Class | Decision Value |
|---|---------|-------------|----------------|
| 1 | Edge Metrics Summary | Core stats | **High** — gates all downstream |
| 2 | Tail Contribution | Concentration risk | **High** — identifies fragile edges |
| 3 | Sequence Monte Carlo | Path dependency | **High** — stress tests ordering |
| 4 | Rolling Windows | Temporal stability | **Medium-High** — detects regime decay |
| 5 | Year-wise PnL | Annual structure | **Medium** — coarse temporal view |
| 6 | Drawdown Anatomy | Capital risk | **High** — recovery factor, duration |
| 7 | Drawdown Composition | DD attribution | **Medium** — useful for portfolio |
| 8 | Streak Analysis | Behavioral risk | **Medium** — losing streak length |
| 9 | Friction Stress | Execution cost | **High** — survivability gate |
| 10 | Directional Robustness | Long/short bias | **Medium** — PF with top-N removed |
| 11 | Early/Late Split | In-sample drift | **Medium** — structural decay check |
| 12 | Symbol Isolation | Concentration risk | **Medium** — single-symbol dependency |
| 13 | Symbol Breakdown | Per-symbol PnL | **Low-Medium** — overlaps with §12 |
| 14 | Block Bootstrap | Statistical confidence | **High** — gold-standard validation |

---

## 3. Seasonality Layers — Structural Justification

### 3.1 Month-of-Year

**Justified: YES (conditional)**

- FX markets exhibit well-documented monthly patterns (January flows, summer liquidity, year-end positioning)
- Mean-reversion strategies (UltimateC family) are sensitive to liquidity cycles
- Breakout strategies (AK series) may show volatility-dependent monthly variation

**Risk:** With 12 buckets and typical trade counts (500–2,000), most monthly cells will have 40–170 trades — barely sufficient for per-cell PF estimation. Below 300 total trades, monthly breakdown is noise.

**Statistical gate:** Only include if total trades ≥ 300. Report PnL + trade count per month; compute chi-squared uniformity test on monthly PnL distribution. P-value > 0.10 → "No significant monthly pattern detected" (one-line verdict). P-value ≤ 0.10 → show full breakdown with flagged months.

### 3.2 Quarter-of-Year

**Justified: NO**

- Quarters are just aggregated months — they carry strictly less information
- If monthly breakdown exists, quarterly is redundant
- Adds visual bulk with no incremental decision value

### 3.3 Day-of-Week

**Justified: YES (conditional)**

- Intraday strategies (1h UltimateC) have session-level structure that maps to weekday patterns
- Mondays/Fridays have documented behavioral differences (gap risk, position squaring)
- 5 buckets vs 12 → higher per-cell sample size → more robust

**Risk:** 4H strategies will have very few trades per weekday per year. Only actionable for 1h or sub-4h timeframes.

**Statistical gate:** Only include if timeframe ≤ 4h AND total trades ≥ 200. Use same chi-squared approach.

---

## 4. Redundancy Analysis — Candidates for Merge/Removal

| Current Section | Issue | Recommendation |
|---|---|---|
| **§5 Year-wise PnL** (inside Rolling) | Already partially covered by §4 Rolling Windows and §11 Early/Late | **MERGE into §4** — add a compact year-wise table as a subsection of Rolling Windows |
| **§13 Symbol Breakdown** | Overlaps heavily with §12 Symbol Isolation | **MERGE into §12** — Symbol Isolation already removes each symbol; adding a PnL table within it is trivial |
| **§7 Drawdown Composition** | Low incremental value over §6 Drawdown Anatomy for single-asset runs | **KEEP for portfolio, SUPPRESS for single-asset** — adaptive section |

**Net effect:** Merging §5 into §4 and §13 into §12 removes 2 standalone sections → frees 2 slots for seasonality.

---

## 5. Proposed Section Count After Integration

| # | Section | Notes |
|---|---------|-------|
| 1 | Edge Metrics Summary | Unchanged |
| 2 | Tail Contribution | Unchanged |
| 3 | Sequence Monte Carlo | Unchanged |
| 4 | Rolling Windows + Year-wise | **Merged** (§4 + old §5) |
| 5 | Drawdown Anatomy | Unchanged |
| 6 | Drawdown Composition | **Portfolio only** — suppressed for single-asset |
| 7 | Streak Analysis | Unchanged |
| 8 | Friction Stress | Unchanged |
| 9 | Directional Robustness | Unchanged |
| 10 | Early/Late Split | Unchanged |
| 11 | Symbol Isolation + Breakdown | **Merged** (old §12 + §13) |
| 12 | Block Bootstrap | Unchanged |
| 13 | **Monthly Seasonality** | **NEW** — conditional on trade count ≥ 300 |
| 14 | **Weekday Seasonality** | **NEW** — conditional on timeframe ≤ 4h AND trades ≥ 200 |

**Total: 14 sections** (same count — 2 merged, 2 added). Maximum possible if all conditions met. Well under the 18-section cap.

---

## 6. Adaptive Behavior

### Single-Asset Runs

- §6 (Drawdown Composition) → **suppressed** (no multi-symbol attribution possible)
- §11 (Symbol Isolation + Breakdown) → **suppressed** (only 1 symbol)
- §13 Monthly → **active if trades ≥ 300**
- §14 Weekday → **active if timeframe ≤ 4h AND trades ≥ 200**
- **Effective count: 10–12 sections**

### Portfolio Runs

- All sections active
- §13/§14 aggregate across symbols (portfolio-level calendar analysis, not per-symbol)
- **Effective count: 12–14 sections**

---

## 7. Statistical Validation Approach

> [!IMPORTANT]
> All seasonality sections must produce a **quantitative verdict**, not a visual heatmap.

### Method: Chi-Squared Uniformity + Effect Size

1. **Null hypothesis:** PnL is uniformly distributed across calendar buckets
2. **Test:** Chi-squared goodness-of-fit on signed PnL counts (positive vs negative) per bucket
3. **Report:** P-value + Cramér's V (effect size)
4. **Verdict logic:**
   - P > 0.10 → `"No significant calendar pattern detected"` (single line, no table)
   - P ≤ 0.10 AND Cramér's V < 0.15 → `"Weak calendar pattern (likely noise)"` (single line)
   - P ≤ 0.10 AND Cramér's V ≥ 0.15 → Show full breakdown table with flagged buckets

### Supplementary Metrics (shown only when pattern detected)

| Column | Purpose |
|---|---|
| Month/Day | Calendar bucket |
| Trades | Sample size per bucket |
| Net PnL | Raw dollar edge |
| PF | Profit factor per bucket |
| Win Rate | Hit rate per bucket |
| **Flag** | ⚠️ if bucket PnL deviates > 1.5σ from mean |

This ensures the section is **zero lines** when no pattern exists, and only expands when statistically justified.

---

## 8. Overfitting Risks

| Risk | Mitigation |
|---|---|
| **Multiple testing** (12 months = 12 implicit hypotheses) | Use Bonferroni-corrected significance or report family-wise p-value |
| **Small-sample illusion** (few trades per bucket → extreme PF values) | Hard gate: suppress section entirely if trades < threshold |
| **Narrative extraction** ("June is always bad") | Report verdict as statistical fact, not actionable filter — explicit disclaimer |
| **Calendar mining** (user adds month filter to strategy) | Disclaimer: `"Calendar patterns are diagnostic only. Adding calendar-based entry/exit filters is prohibited under parameter_mutation: prohibited."` |
| **Survivorship bias in calendar buckets** | Out-of-sample cross-validation not feasible with calendar data; acknowledge limitation |

> [!CAUTION]
> The single greatest overfitting risk is that a human reads "Q1 is profitable" and mentally anchors future decisions on 8 data points. The verdict system above is specifically designed to prevent this by suppressing weak signals.

---

## 9. What This Does NOT Require

- ❌ No changes to trading engine
- ❌ No new indicators
- ❌ No parameter changes
- ❌ No modifications to `strategy.py` files
- ✅ Reads existing `deployable_trade_log.csv` only (already contains `entry_timestamp`, `exit_timestamp`, `pnl_usd`)

---

## 10. Recommendation

**ADD WITH CONSTRAINTS**

Seasonality diagnostics add structurally justified signal **only when**:

1. Trade count exceeds minimum thresholds (300 monthly, 200 weekday)
2. Statistical test gates suppress noise (chi-squared + effect size)
3. Output is verdict-first (zero lines when no pattern; compact table when pattern detected)
4. Quarterly breakdown is excluded (redundant with monthly)
5. Two existing low-signal sections are merged to maintain section budget

The conditional suppression mechanism ensures the report stays concise for thin-sample strategies (like UltimateC_RegimeFilter_FX with 650 trades) while providing useful diagnostics for high-trade-count strategies (like AK36 with 6,500+ trades).
