# Seasonality Diagnostics — Revised Structural Proposal (v2)

**Supersedes:** SEASONALITY_DIAGNOSTICS_PROPOSAL.md (v1)
**Scope:** Timeframe-agnostic, horizon-aware, deployment-relevant

---

## Phase 1 — Timeframe Governance

Seasonality layers activate based on signal timeframe. The system reads `timeframe` from the strategy identity — no manual configuration.

| Timeframe | Monthly | Weekday | Rationale |
|-----------|---------|---------|-----------|
| 1H | ✅ (gated) | ✅ (gated) | High bar density → sufficient per-bucket samples |
| 4H | ✅ (gated) | ✅ (conditional) | ~6 bars/day → weekday buckets viable if trade density sufficient |
| Daily | ✅ (gated) | ❌ | 1 bar/day → weekday buckets have ≤ ~52 entries/year, too sparse |
| Weekly+ | ✅ (gated) | ❌ | Same reasoning, worse |

**Gating rule:** "✅ (gated)" means the section renders only if Phase 2 trade-count thresholds are met. "✅ (conditional)" means an additional density check: weekday analysis on 4H requires `total_trades / 5 ≥ 40` (i.e., ≥ 200 trades, ensuring ≥ 40 average per weekday bucket).

**Quarterly:** Excluded at all timeframes. Strictly redundant with monthly; 4 buckets yield no incremental insight over 12.

---

## Phase 2 — Trade Count & Bucket Gating

### Global Thresholds

| Analysis | Minimum Total Trades | Per-Bucket Minimum |
|----------|---------------------|-------------------|
| Monthly | ≥ 300 | ≥ 20 per month |
| Weekday | ≥ 200 | ≥ 20 per day |

### Justification

- **300 monthly:** 12 buckets × 25 trades = 300. At 25 trades/bucket, PF estimation has ~±0.3 sampling error (acceptable for diagnostic, not for decisioning). 20 is the hard floor per bucket.
- **200 weekday:** 5 buckets × 40 trades = 200. More concentrated → smaller per-bucket variance.
- **20 per-bucket minimum:** Below 20, win-rate and PF are dominated by individual outliers. Suppressed buckets are marked `[insufficient]` in the table.

### Behavior When Thresholds Not Met

If global threshold fails → **Dispersion Summary Only** (no table, no verdict):

```
Monthly Seasonality: SUPPRESSED (187 trades < 300 threshold)
  Dispersion: max month deviation ±$42.30 from mean ($18.50/month)
```

This preserves signal about whether calendar variation *exists* without making false-precision claims.

---

## Phase 3 — Horizon Awareness

The backtest duration determines what exposure decisions the seasonality section may recommend.

### Mode Detection

Computed from `exit_timestamp.max() - entry_timestamp.min()`:

| Duration | Mode | Label |
|----------|------|-------|
| < 2 years | `SHORT` | `⚠️ SHORT MODE — Informational only` |
| 2–5 years | `MEDIUM` | `MEDIUM MODE — Throttle decisions allowed` |
| > 5 years | `FULL` | `FULL MODE — Full decision logic` |

### Mode Behavior

| Mode | Statistical Test | Stability Test | Exposure Decision |
|------|-----------------|----------------|-------------------|
| SHORT | Run test, show result | Skip (insufficient data) | ❌ None — display only |
| MEDIUM | Run test, show result | Skip (single split unreliable) | Throttle only (0.5x) |
| FULL | Run test, show result | **Required** (Phase 4) | Full range (0x, 0.5x, 1x) |

### Display

The mode badge appears at the top of each seasonality section:

```
## Section 13 — Monthly Seasonality [FULL MODE]
```

---

## Phase 4 — Stability Across Subperiods

**Applies only in FULL MODE (> 5 years).**

### Method

1. Split the trade log chronologically at the midpoint by trade count (not date — ensures equal sample size)
2. Compute monthly/weekday PnL distribution independently for each half
3. For any bucket flagged as anomalous in the full sample, check whether the directional effect (positive/negative PnL) is **consistent** across both halves

### Consistency Test

A flagged bucket is **stable** if:

- Same PnL sign in both halves, AND
- PnL magnitude in the weaker half ≥ 25% of the stronger half

A flagged bucket is **unstable** if either condition fails.

### Consequences

| Stability | Action |
|-----------|--------|
| All flagged buckets stable | Verdict stands; exposure decisions allowed |
| Any flagged bucket unstable | Downgrade entire section to `INFORMATIONAL` — no exposure decisions |
| Mixed (some stable, some not) | Show per-bucket stability column; only stable buckets eligible for exposure decisions |

### Display

```
| Month | Trades | Net PnL | PF | Flag | H1 PnL | H2 PnL | Stable |
|-------|--------|---------|-----|------|--------|--------|--------|
| Jun   | 84     | -$280   | 0.72| ⚠️   | -$190  | -$90   | ✅     |
| Nov   | 91     | -$45    | 0.94| —    | —      | —      | —      |
```

---

## Phase 5 — Statistical Method

### Primary Test: Kruskal-Wallis H-test

**Why not chi-squared?** Chi-squared on signed counts (win/loss per bucket) discards magnitude. A month with many small wins and one catastrophic loss would pass chi-squared but show a clear negative edge. Kruskal-Wallis operates on PnL magnitudes non-parametrically — better suited.

**Why not ANOVA?** Trade PnL distributions are heavy-tailed and non-normal. ANOVA's normality assumption is violated. Kruskal-Wallis is the rank-based equivalent, robust to skew.

### Test Pipeline

```
1. Kruskal-Wallis H-test on PnL grouped by calendar bucket
   → H-statistic, p-value
2. Effect size: η² = (H - k + 1) / (N - k)
   where k = number of buckets, N = total trades
3. Dispersion: max |bucket_mean - global_mean| / global_std
```

### Verdict Logic

| p-value | η² | Verdict |
|---------|-----|---------|
| > 0.10 | any | `No significant calendar pattern` (1 line) |
| ≤ 0.10 | < 0.02 | `Weak pattern detected (low effect size)` — show table, no decisions |
| ≤ 0.10 | ≥ 0.02 | `Significant calendar pattern` — show table + flag anomalous buckets |

### Bucket Flagging

A bucket is flagged (⚠️) if:

- Bucket mean PnL deviates > 1.5σ from global mean, AND
- Bucket trade count ≥ 20

> [!TIP]
> **Suggestion:** Consider pre-computing per-bucket volatility-adjusted PnL (divide each trade's PnL by the ATR at entry, if available in the trade log). This would control for "June is bad because June is volatile" — a calendar pattern that is actually a volatility pattern already captured by the regime breakdown. This is optional and depends on whether `atr_at_entry` is available in the deployable trade log.

---

## Phase 6 — Section Rationalization

### Current Inventory (14 sections)

| # | Section | Recommendation |
|---|---------|---------------|
| 1 | Edge Metrics Summary | **KEEP** — core gate |
| 2 | Tail Contribution | **KEEP** — concentration risk |
| 3 | Sequence Monte Carlo | **KEEP** — path dependency |
| 4 | Rolling Windows | **KEEP + ABSORB** Year-wise PnL (old §5) |
| 5 | Year-wise PnL | **MERGE → §4** as subsection |
| 6 | Drawdown Anatomy | **KEEP** |
| 7 | Drawdown Composition | **KEEP** (portfolio) / **SUPPRESS** (single-asset) |
| 8 | Streak Analysis | **COMPRESS** — reduce to 3 lines: max win streak, max loss streak, avg loss streak |
| 9 | Friction Stress | **KEEP** — survivability gate |
| 10 | Directional Robustness | **COMPRESS** — reduce to 4 lines: long/short split + PF without top-20 |
| 11 | Early/Late Split | **KEEP** — structural decay |
| 12 | Symbol Isolation | **KEEP + ABSORB** Symbol Breakdown (old §13) |
| 13 | Symbol Breakdown | **MERGE → §12** as inline table |
| 14 | Block Bootstrap | **KEEP** — gold-standard validation |

### Revised Inventory (≤ 15 sections)

| # | Section | Status |
|---|---------|--------|
| 1 | Edge Metrics Summary | Unchanged |
| 2 | Tail Contribution | Unchanged |
| 3 | Sequence Monte Carlo | Unchanged |
| 4 | Rolling Windows + Year-wise | Merged |
| 5 | Drawdown Anatomy | Unchanged |
| 6 | Drawdown Composition | Adaptive (portfolio only) |
| 7 | Streak Analysis | Compressed (3 lines) |
| 8 | Friction Stress | Unchanged |
| 9 | Directional Robustness | Compressed (4 lines) |
| 10 | Early/Late Split | Unchanged |
| 11 | Symbol Isolation + Breakdown | Merged |
| 12 | Block Bootstrap | Unchanged |
| 13 | **Monthly Seasonality** | **NEW** — gated |
| 14 | **Weekday Seasonality** | **NEW** — gated, timeframe-conditional |
| — | *Max if all active* | **14** |

Even with Drawdown Composition active on portfolio runs → **15 max**. Within target.

---

## Phase 7 — Deployment Decision Framework

### Exposure Decision Matrix

An exposure recommendation can only be produced when **all five gates pass**:

| Gate | Requirement |
|------|-------------|
| **G1: Statistical significance** | Kruskal-Wallis p ≤ 0.10 |
| **G2: Effect size** | η² ≥ 0.02 |
| **G3: Stability** | Flagged bucket is stable across subperiods (Phase 4) |
| **G4: Sample size** | Flagged bucket has ≥ 20 trades |
| **G5: Not volatility-explained** | Bucket's negative PnL is not fully explained by high-vol regime concentration (if vol-conditioned data available) |

### Decision Outputs

| All 5 gates pass? | Horizon Mode | Output |
|---|---|---|
| No | Any | `No action` |
| Yes | SHORT | `No action` (informational only) |
| Yes | MEDIUM | `Consider reducing exposure to 0.5x during [bucket]` |
| Yes | FULL | `Consider avoiding [bucket]` OR `Reduce to 0.5x during [bucket]` |

### Throttle vs Avoid

| Condition | Decision |
|-----------|----------|
| Bucket mean PnL < 0 AND bucket PF < 0.85 | **Avoid** (0x exposure) |
| Bucket mean PnL < 0 AND 0.85 ≤ bucket PF < 1.0 | **Throttle** (0.5x exposure) |
| Bucket PF ≥ 1.0 | **No action** (not a negative-edge bucket) |

> [!CAUTION]
> Exposure decisions are **recommendations to the human operator**, not automated engine changes. The engine does not read these outputs. Implementation of throttling/avoidance is manual and requires operator judgment.

---

## Phase 8 — Portfolio vs Single-Asset Behavior

### Section Activation Matrix

| Section | Single-Asset | Portfolio |
|---------|-------------|-----------|
| §6 Drawdown Composition | ❌ Suppressed | ✅ Active |
| §11 Symbol Isolation + Breakdown | ❌ Suppressed | ✅ Active |
| §13 Monthly Seasonality | ✅ Asset-level | ✅ Portfolio-level aggregate |
| §14 Weekday Seasonality | ✅ Asset-level | ✅ Portfolio-level aggregate |

### Portfolio Seasonality Rules

- Aggregate PnL across all symbols per calendar bucket — **no per-symbol calendar slicing**
- Rationale: Per-symbol × per-month creates N×12 cells, destroying sample size
- If a symbol contributes < 10% of total trades, its calendar weight is naturally diluted — no special handling needed

### Single-Asset Seasonality

- Standard analysis on the single symbol's trade log
- §11 (Symbol Isolation) suppressed (only 1 symbol — nothing to isolate)
- All other sections active per normal gating rules

---

## Summary Tables

### Gating Logic Summary

| Check | Source | Threshold |
|-------|--------|-----------|
| Timeframe → weekday eligibility | `strategy.timeframe` | ≤ 4H |
| Monthly section activation | `len(tr_df)` | ≥ 300 |
| Weekday section activation | `len(tr_df)` | ≥ 200 |
| Per-bucket suppression | `bucket_trade_count` | ≥ 20 |
| 4H weekday density | `total_trades / 5` | ≥ 40 |
| Horizon mode | `max_exit - min_entry` | < 2y / 2-5y / > 5y |
| Stability required | Horizon mode | FULL only |

### Statistical Method Summary

| Component | Method |
|-----------|--------|
| Primary test | Kruskal-Wallis H-test (non-parametric) |
| Effect size | η² (eta-squared from H-statistic) |
| Dispersion | max bucket deviation / global σ |
| Bucket flagging | > 1.5σ deviation + ≥ 20 trades |
| Stability | Chronological half-split, same-sign + 25% magnitude |

### Exposure Decision Matrix

```
                 ┌──────────────┐
                 │ Statistical  │
                 │ test passes? │
                 └──────┬───────┘
                        │
              No ───────┼──────── Yes
              │                    │
        [No action]         ┌──────┴───────┐
                            │ Effect size  │
                            │ η² ≥ 0.02?  │
                            └──────┬───────┘
                                   │
                         No ───────┼──────── Yes
                         │                    │
                   [No action]         ┌──────┴───────┐
                                       │ Stable across│
                                       │ subperiods?  │
                                       └──────┬───────┘
                                              │
                                    No ───────┼──────── Yes
                                    │                    │
                              [Informational     ┌──────┴───────┐
                               only]             │ Horizon Mode │
                                                 └──────┬───────┘
                                                        │
                                    SHORT ──── MEDIUM ──── FULL
                                      │          │          │
                                [No action]  [0.5x only] [0x or 0.5x
                                                          per PF rule]
```

---

## Final Recommendation

**ADD WITH CONSTRAINTS**

The revised proposal addresses all structural concerns:

1. **Timeframe-agnostic** — weekday auto-suppresses on daily+; monthly works everywhere
2. **Sample-size gated** — hard floors prevent small-sample false signals
3. **Horizon-aware** — SHORT/MEDIUM/FULL modes prevent overreading thin history
4. **Compact** — 14–15 sections max via merges and compressions
5. **Deployment-relevant** — explicit 5-gate decision framework for exposure throttling
6. **Engine-independent** — reads trade logs only, outputs human recommendations

The system is designed to produce **zero output** for most strategies (those with no calendar signal) and to be **maximally conservative** when it does produce exposure recommendations.
