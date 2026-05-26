# Pine N=30 Family-Density Analysis — Broad Cohort Pass

**Date:** 2026-05-26
**Strategy:** `pine_ratio_zrev_v1` at N=30, 15m, entry_mode=absolute
**Cohort:** 87 pairs (252-only ≥30d alignment from screener History tab; BTC/ETH/XAU excluded)
**Window per pair:** the pair's own latest continuous 252d-aligned period from the History tab
**Evaluation:** Ret/DD ranking — governance verdict (CORE/WATCH/FAIL) intentionally ignored because the screening rules are deployment-scale gates, not research evaluators

## Headline results

The broad-cohort pass overturns the prior "falsified" framing decisively. **The strategy has clear edge on FX-FX and IDX-IDX surfaces; CROSS is structurally hostile.** Specifically:

| Class | N | Mean Ret/DD | Median | % positive | % > 1.0 | % > 2.0 |
|---|---|---|---|---|---|---|
| **FX-FX** | 29 | **+0.83** | +0.29 | **62%** | 28% | 21% |
| **IDX-IDX** | 6 | **+0.98** | +0.82 | **67%** | 33% | **33%** |
| **CROSS** (FX-IDX) | 52 | −0.30 | −0.53 | 27% | 4% | 4% |

The CROSS class accounts for 60% of the cohort and pulls the unconditional mean negative — but conditional on class, FX-FX and IDX-IDX both show real and dense positive signal.

## Top 10 individual performers (Ret/DD)

| Rank | Pair | Class | Net % | DD % | **Ret/DD** | Trades |
|---|---|---|---|---|---|---|
| **1** | **AUDJPY/USDCHF** | FX | +145.1 | 15.9 | **9.12** | 276 |
| 2 | EURGBP/GBPNZD | FX | +43.2 | 14.5 | 2.98 | 140 |
| 3 | ESP35/JPN225 | IDX | +90.0 | 33.4 | 2.69 | 36 |
| 4 | **GBPJPY/GER40** | CROSS | +70.1 | 27.9 | **2.52** | 86 |
| 5 | AUDNZD/USDCHF | FX | +33.7 | 14.4 | 2.35 | 118 |
| 6 | EUSTX50/FRA40 | IDX | +36.9 | 16.0 | 2.31 | 168 |
| 7 | **CHFJPY/GER40** | CROSS | +58.2 | 25.3 | **2.31** | 84 |
| 8 | AUDJPY/EURUSD | FX | +37.1 | 17.8 | 2.09 | 118 |
| 9 | EURGBP/USDCAD | FX | +14.4 | 7.1 | 2.03 | 92 |
| 10 | NZDJPY/USDCHF | FX | +44.9 | 22.2 | 2.03 | 112 |

## Family-density findings (where positive performers cluster)

### Family: **USDCHF-as-hedge-leg** (NEW DISCOVERY)

Not in my pre-defined family list but the data surfaces it strongly. **Pairs where USDCHF is one leg show consistent positive signal across yen-cross and Antipodean FX legs:**

| Pair | Net % | DD % | Ret/DD |
|---|---|---|---|
| AUDJPY/USDCHF | +145.1 | 15.9 | **9.12** |
| AUDNZD/USDCHF | +33.7 | 14.4 | 2.35 |
| NZDJPY/USDCHF | +44.9 | 22.2 | 2.03 |
| CADJPY/USDCHF | +34.3 | 19.3 | 1.78 |
| CHFJPY/USDCHF | +28.3 | 16.5 | 1.71 |
| EURAUD/USDCHF | +9.5 | 20.0 | 0.48 |
| EURJPY/USDCHF | +8.8 | 41.3 | 0.21 |
| GBPAUD/USDCHF | −1.0 | 37.5 | −0.03 |
| AUDUSD/USDCHF | −58.4 | 75.7 | −0.77 |
| GBPJPY/USDCHF | −52.3 | 67.5 | −0.78 |

10 USDCHF-leg pairs, **60% positive Ret/DD, 50% > Ret/DD 1.0, 30% > 2.0** — comparable to or better than the structural class averages. This is a real sub-family.

**Hypothesis on mechanism:** CHF strengthens during risk-off events alongside JPY (both safe-haven currencies). For a yen-cross like AUDJPY, the spread vs USDCHF essentially trades "risk-on/risk-off divergence between AUD-bloc and CHF" — and this property is mean-reverting at intraday scale when the two safe-havens stay correlated. The failure cases (AUDUSD/USDCHF, GBPJPY/USDCHF) are pairs where the structural divergence isn't intuitive (AUDUSD has USD on both sides so the "spread" is a forex-vs-forex-with-USD-cancellation oddity).

### Family: **EU-IDX × EU-IDX** (same-session indices)

| Pair | Net % | DD % | Ret/DD |
|---|---|---|---|
| EUSTX50/FRA40 | +36.9 | 16.0 | 2.31 |
| ESP35/UK100 | +19.2 | 23.1 | 0.83 |
| ESP35/FRA40 | +19.4 | 23.8 | 0.81 |
| ESP35/GER40 | −14.1 | 36.0 | −0.39 |
| ESP35/EUSTX50 | −10.3 | 26.2 | −0.39 |

5 pairs, **60% positive, mean Ret/DD +0.63**. Smaller-and-mixed family but confirms the "same-session, similar structure" hypothesis. The two ESP35-failures (vs GER40 and EUSTX50) need investigation — interestingly, those pairs include ESP35 in both, and EUSTX50 contains some Spanish components, so the spread may be quasi-tautological.

### Family: **GER40 vs Yen-cross FX** (CROSS-outlier surprise)

| Pair | Net % | DD % | Ret/DD |
|---|---|---|---|
| GBPJPY/GER40 | +70.1 | 27.9 | **2.52** |
| CHFJPY/GER40 | +58.2 | 25.3 | **2.31** |
| EURGBP/GER40 | +20.9 | 39.7 | 0.53 |
| GBPNZD/GER40 | +14.1 | 37.0 | 0.38 |
| CADJPY/GER40 | +14.7 | 43.6 | 0.34 |
| AUDNZD/GER40 | +7.7 | 48.8 | 0.16 |
| EURJPY/GER40 | +5.3 | 40.6 | 0.13 |
| AUDUSD/GER40 | −24.7 | 55.5 | −0.45 |
| AUDJPY/GER40 | −31.7 | 71.2 | −0.45 |
| EURAUD/GER40 | −30.5 | 88.7 | −0.34 |
| GBPUSD/GER40 | −29.3 | 100.5 | −0.29 |
| EURUSD/GER40 | +3.1 | 66.2 | 0.05 |
| GBPAUD/GER40 | −13.2 | 81.2 | −0.16 |

**13 pairs, 62% positive Ret/DD** — within the broadly-hostile CROSS class. The yen-crosses with GBP or CHF as the partner currency consistently work (GBPJPY/GER40 at 2.52, CHFJPY/GER40 at 2.31). The AUD-anchored pairs consistently fail. **GER40 doesn't share FRA40's catastrophic CROSS failure pattern.** Hypothesis: GER40 has more "FX-aware" trading hours (electronic trading session aligns with London hours where FX volume peaks), giving the spread cleaner intraday MR than FRA40 vs FX.

### Family: **FRA40 vs FX (any)** (CONFIRMED structural failure mode)

| Pair | Ret/DD |
|---|---|
| CHFJPY/FRA40 | −0.95 |
| EURJPY/FRA40 | −0.92 |
| AUDNZD/FRA40 | −0.94 |
| EURGBP/FRA40 | −0.94 |
| EURUSD/FRA40 | −0.87 |
| CADJPY/FRA40 | −0.78 |
| AUDJPY/FRA40 | −0.77 |
| AUDUSD/FRA40 | −0.53 |
| FRA40/USDCHF | −0.89 |

**9 pairs, 0% positive Ret/DD, mean -0.84, all catastrophic.** The session-mismatch hypothesis is confirmed empirically: FRA40 paired with any 24-hour FX leg is a structural fail. **Do not test FRA40 vs FX further.** The contrast with the 60% positive rate on EU-IDX × EU-IDX (where FRA40 paired with another European index works fine) localizes the problem to the cross-class leg-structure mismatch, not FRA40 itself.

### Family: Triangular GBP-cancellation (small N but signal)

Only 1 pair (EURGBP/GBPNZD) had this exact structure in the cohort. Ret/DD 2.98. The cohort doesn't have enough triangular pairs to draw a family verdict — would need explicit follow-up.

## Class-level confirmations

| Confirmation | Evidence |
|---|---|
| FX-FX has tradeable edge | 18/29 positive Ret/DD; 8 pairs >1.0; 6 pairs >2.0 |
| IDX-IDX has tradeable edge | 4/6 positive Ret/DD; 2 pairs >1.0; 2 pairs >2.0; small N caveat |
| CROSS is structurally hostile | 14/52 positive (27%); only 2 pairs >2.0 (both GER40-yen-cross outliers); mean Ret/DD -0.30 |
| Cost burden is real but doesn't kill edge on right pairs | Best FX-FX pairs (Ret/DD 9, 3, 2) easily compensate for ~2.8 trades/day cost |

## Implications for strategy character

The data resolves what edge the strategy actually has:

1. **Spread mean-reversion works at the 15m / N=30 scale when both legs share trading structure** (same session, 24-hour-vs-24-hour, similar liquidity profile). Cross-class spreads with session-misaligned legs fail because the spread isn't stationary at the trading TF.

2. **The screener's daily cointegration is a NECESSARY but not SUFFICIENT condition.** All 87 pairs were 252d-cointegrated at daily TF — but only the structurally-symmetric ones produced edge at 15m. The cointegration-vs-microstructure-MR signal-class distinction (per [project_cointegrated_pair_pine_defaults.md](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\project_cointegrated_pair_pine_defaults.md)) was correct — daily cointegration *gates* the pair-pair universe but doesn't determine which work at intraday scale.

3. **The TradingView CHFJPY/UK100 visual that started this thread (Ret/DD −0.54 in the pipeline) was a false positive** — the visual test happened to look favorable on a chart segment, but the structural class (yen-cross-FX × European-IDX) is largely hostile in this strategy class.

## Recommended next moves

In priority order:

### 1. Deep-dive AUDJPY/USDCHF (the standout outlier, Ret/DD 9.12)

This is an extreme positive result that needs scrutiny before any deployment thought:
- Is it data-genuine or artifact? Look at per-trade behavior; are gains evenly distributed across the test window or concentrated in 1-2 events?
- What does the spread structurally look like? AUDJPY is risk-on, USDCHF is risk-off. The pair effectively trades "AUD-bloc vs CHF" with USD/JPY cancellation. Is there a known macro reason this would be mean-reverting at 15m?
- If genuine: cross-window check (run on prior 90-day windows where the pair was also 252d-cointegrated, if any exist in the History tab — currently capped at 91d so no).

### 2. Expand USDCHF-hedge cohort

The USDCHF-leg sub-family shows 5 of 10 pairs at Ret/DD > 1.0. Worth confirming with adjacent pairs:
- Add USDCHF/EUR... wait, no — we already have EURJPY/USDCHF (0.21) and EURAUD/USDCHF (0.48). Both modest.
- The pattern is specifically yen-cross-or-Antipodean × USDCHF works; USD-anchored × USDCHF doesn't (AUDUSD/USDCHF −0.77).
- This is a useful empirical taxonomy for future spread-strategy design.

### 3. Investigate GER40-vs-yen-cross sub-family (CROSS outlier)

GBPJPY/GER40 and CHFJPY/GER40 both >2.3 Ret/DD challenge the broad CROSS-hostile finding. Three possibilities:
- These are real edge on a specific FX×IDX micro-structure (worth more research)
- They're statistical outliers from a small sample
- The strategy works against GER40 because GER40 has different session structure than FRA40

A follow-up could test all yen-cross × GER40 pairs systematically (only one extra needed: NZDJPY/GER40 if not already in cohort).

### 4. NOT promote any of these for live deployment yet

Even AUDJPY/USDCHF's Net +145% over 91 days at $1000 stake = $1450 — would pass CORE governance for that pair alone. But the strategy class needs cross-window robustness validation first. **The current History tab only covers 90 days of confirmed-aligned data**. Promoting based on a single 90-day aligned window is premature; we need the History tab to accumulate (per the user's earlier note: "later we can populate the historical window to more depth and then have longer period tests").

## What changed in the framework this session

| Insight | What it lets future research do |
|---|---|
| Use Ret/DD ranking, not governance verdicts, for research evaluation | Don't mistake "deployment-scale fails" for "no edge" |
| Test per-pair on alignment-window from History tab | Methodology-clean: tests run when the precondition holds |
| Analyze family density, not isolated winners | Surfaces structural patterns (USDCHF-hedge family, FRA40-vs-FX failure mode); isolates noise from signal |
| Class-conditional analysis matters when one class dominates the cohort numerically | CROSS pulls the unconditional mean negative; per-class view shows FX-FX/IDX-IDX are productive |

## Provenance

- Pipeline: 4 sub-batches over 2026-05-26 (initial batch 1 with 22 directives; batch 2/3 cleanup; cohort expansion batch 4 with 63 fresh + 14 prior results).
- All 87 results in `basket_sheet` table of `TradeScan_State/ledger.db` (`directive_id LIKE '%15M_COINTREV_V3_L30%'`).
- Analysis script: `tmp/family_density_analysis.py`; results parquet at `tmp/family_density_results.parquet`.
- Excluded: BTCUSD, ETHUSD, XAUUSD-containing pairs (H2RecycleRuleV3 currency-reference table issue, separate tech-debt item).
