# S21 P06/P07/P08 Transferability Validation

**Date:** 2026-05-26  
**Goal:** does the EURUSDUSDJPY S21 deployment baseline edge transfer structurally to
GBPUSDUSDJPY (yen-cross sibling) and AUDUSDUSDCAD (commodity-currency cross)?

**Method:** pure transferability — identical S21 deployment-baseline params
(h3_spread@3, 15m, entry_delay_bars=8, extreme_z=5.0, reentry_z=1.0,
vol_neutral_sizing=true) ported unchanged. No tuning, no parameter changes,
no screener changes.

**Constraints noted:**

- AUDUSD + USDCAD 15m data starts 2024-05; only Window A (2024-05→2026-05) testable.
  Cross-window evaluation for AUDUSDUSDCAD is therefore impossible — single window only.
- GBPUSDUSDJPY has 15m data 2016-onward; all 3 windows tested.

## Headline results

### Window A — 2024-05-18 → 2026-05-18

| Pair | Verdict | Net % | Max DD % | Ret/DD | Trades | Cycles | Cycle Win % | Final $ | Peak winner lot |
|---|---|---|---|---|---|---|---|---|---|
| EUR baseline P06 (E003) | CORE | 201.06 | 30.33 | 6.63 | 522 | 237.00 | 25.74 | 3010.61 | 0.46 |
| GBP transfer P06 | CORE | 317.28 | 20.43 | 15.53 | 588 | 260.00 | 29.23 | 4172.81 | 0.34 |
| AUD transfer P06 | FAIL | -71.90 | 95.52 | -0.75 | 626 | 279.00 | 22.94 | 281.02 | 0.40 |

### Window B — 2021-05-18 → 2023-05-18

| Pair | Verdict | Net % | Max DD % | Ret/DD | Trades | Cycles | Cycle Win % | Final $ | Peak winner lot |
|---|---|---|---|---|---|---|---|---|---|
| EUR baseline P07 (E003) | CORE | 305.63 | 20.31 | 15.05 | 632 | 283.00 | 24.73 | 4056.30 | 0.49 |
| GBP transfer P07 | FAIL | 150.49 | 66.24 | 2.27 | 660 | 309.00 | 22.98 | 2504.93 | 0.73 |

### Window C — 2018-05-18 → 2020-05-18

| Pair | Verdict | Net % | Max DD % | Ret/DD | Trades | Cycles | Cycle Win % | Final $ | Peak winner lot |
|---|---|---|---|---|---|---|---|---|---|
| EUR baseline P08 (E003) | FAIL | -142.71 | 123.53 | -1.16 | 636 | 291.00 | 26.12 | -427.14 | 0.34 |
| GBP transfer P08 | FAIL | -72.32 | 91.55 | -0.79 | 616 | 293.00 | 22.87 | 276.81 | 0.89 |

## Cycle / recycle behavior

| Pair / Window | Trades | Cycles | Recycle events | Cycle Win % | Peak winner lot | Final realized $ |
|---|---|---|---|---|---|---|
| EUR baseline P06 (E003) (A) | 522 | 237.00 | 3747 | 25.74 | 0.4600 | 113.79 |
| GBP transfer P06 (A) | 588 | 260.00 | 4676 | 29.23 | 0.3400 | 1573.74 |
| AUD transfer P06 (A) | 626 | 279.00 | 2926 | 22.94 | 0.4000 | -1669.77 |
| EUR baseline P07 (E003) (B) | 632 | 283.00 | 4353 | 24.73 | 0.4900 | 466.28 |
| GBP transfer P07 (B) | 660 | 309.00 | 4790 | 22.98 | 0.7300 | -1211.72 |
| EUR baseline P08 (E003) (C) | 636 | 291.00 | 3165 | 26.12 | 0.3400 | -2364.78 |
| GBP transfer P08 (C) | 616 | 293.00 | 4323 | 22.87 | 0.8900 | -1618.33 |

## Interpretation

### Per-pair verdict

**GBPUSDUSDJPY — partial transfer; window-conditional.** Window A actually *beats* the EUR baseline (Net +317 vs +201, DD 20 vs 30, Ret/DD 15.5 vs 6.6). Cycle counts, recycle counts, and cycle-win-rate are within ±15% of EUR — the mechanic fires the same way, just with more profitable cycles in 2024-2026. But Window B is a hard fail (Net +150 vs +306 EUR, DD blows out 66% vs 20%, Ret/DD collapses 2.3 vs 15.0). Window C matches EUR's regime-hostile FAIL — same direction, modestly less bad. Net read: the yen-cross sibling thesis holds for the post-2024 macro regime but **does not survive the 2021-2023 window**. The strategy is not portable across windows even within the yen-cross class.

**AUDUSDUSDCAD — catastrophic fail.** Window A: Net -72, DD 96%, Ret/DD -0.75, peak-winner-lot 0.40, final realized $-1670. Trade and cycle counts are similar to GBP/EUR (the mechanic fires), so this isn't a "didn't trade" failure — it's a "wrong-direction outcome on similar trade frequency" failure. The commodity-currency cross is a different structural class than yen-crosses; the spread mean-reversion edge that exists on EUR/USDJPY does not exist on AUD/USDCAD with the same parameters. **Window B/C were not testable** due to 15m data starting 2024-05.

### Cross-window consistency (GBPUSDUSDJPY-only since AUD has 1 window)

| Window | EUR Net% | GBP Net% | Δ Net% | EUR DD% | GBP DD% | Δ DD% | Verdict transfer |
|---|---|---|---|---|---|---|---|
| A (2024-26) | +201 | **+317** | **+116** | 30 | **20** | -10 | CORE → CORE (improves) |
| B (2021-23) | +306 | +150 | **-156** | 20 | **66** | **+46** | CORE → FAIL (degrades) |
| C (2018-20) | -143 | -72 | +71 | 124 | 92 | -32 | FAIL → FAIL (matches) |

The Window-A-best, Window-B-worst, Window-C-matches pattern says the GBP edge correlates with *recent* macro alignment but breaks during the 2021-2023 dollar-cycle window. The 46pp DD swing between Window A and B on the same pair is a strong structural warning: this isn't a noise difference, it's a regime-dependent edge.

### Cycle behavior similarity (mechanic vs outcome)

The recycle mechanic ports cleanly: trade counts (522-660), cycle counts (237-309), cycle win rate (22.9-29.2%) cluster tightly across all 4 new runs and the EUR baseline. **The strategy executes the same way on every pair-pair.** What changes is the PnL distribution per cycle:

- GBP Win A: cycle wins compound favorably → +$1,574 realized + paper gains to +$317% Net
- GBP Win B: cycle wins exist but cycle losses are larger and longer → +$2,505 final equity but DD path is unacceptable
- AUD Win A: cycles run; outcomes are inverted → -$1,670 realized, peak winner lot 0.40 with no compounding upside

This pattern points to **the spread-mean-reversion thesis itself being the variable**, not the mechanic. When the spread mean-reverts (EUR Win A, GBP Win A) the strategy compounds. When it trends (GBP Win B, AUD Win A) the strategy bleeds because cycles repeatedly reverse-cross into adverse PnL.

### Failure modes identified

1. **GBP Win B DD blow-out (66%):** GBP/USDJPY spread regime changed materially in 2021-2023 (Brexit aftermath + BoJ pivot + USD-cycle rotation). The vol_neutral_sizing param doesn't protect against trending spread environments. The mechanic keeps re-entering after each adverse exit because cross-watch + macro filter both still align.
2. **AUD/USDCAD non-transferability:** the AUD-CAD spread does not exhibit yen-cross-like mean reversion. Commodity-currency cross-dynamics are driven by oil/iron-ore correlation and central-bank rate differentials — different mechanism entirely. The strategy mistakenly treats AUD-vs-CAD spread divergences as MR opportunities.
3. **Peak winner lot 0.73 (GBP B) / 0.89 (GBP C) vs 0.49 / 0.34 EUR:** the loser-leg pyramid grew larger in the GBP failures than in EUR success — consistent with the martingale-tail risk flagged in [[project_h2_recycle_martingale_tail]]. Larger pyramid → larger loss when the spread doesn't revert.

### Promotion implications

- **The S21 deployment baseline is NOT portfolio-grade as a multi-pair construct.** Even sibling-class transfer (GBP/USDJPY) is window-conditional with a major DD blow-out in Window B.
- **The S21 baseline is candidate-grade for EURUSDUSDJPY specifically**, with documented Window-A-best behavior + acknowledged Window-C regime hostility.
- **AUDUSDUSDCAD is OUT** — wrong structural class, no edge. Do not pursue.
- **GBPUSDUSDJPY Window-A-only deployment** could be considered as a sibling track to EUR, but the Window B failure means it would have to come with an explicit regime-conditional posture (operator-gated like Window C currently is).

### Recommended next steps

1. **Promote EURUSDUSDJPY S21 P06/P07 only.** Window C remains operator-gated. This is single-pair promotion, not portfolio promotion.
2. **Park GBPUSDUSDJPY transferability.** The Win A→B inconsistency tells us the edge is regime-dependent. A productive follow-on arc would be: what is structurally different in 2021-2023 vs 2024-2026 GBP-yen-cross dynamics? But that's a research arc, not a deployment path.
3. **Drop AUDUSDUSDCAD as a yen-cross-derivative target.** The commodity-currency-cross class needs a fundamentally different strategy if it's worth pursuing at all.
4. **Per `feedback_promote_quality_gate`:** before any actual promotion, run the individual-trade quality gates (tail concentration, flat periods, edge ratio) on EURUSDUSDJPY P06/P07. The composite metrics passing isn't sufficient — particularly given the cross-pair fragility this test surfaced.
5. **N=30 Pine port** (deferred secondary item) becomes the next research arc. The transferability of the H3_spread@3 mechanic is now bounded; the N=30 micro-MR signal is a different strategy class and deserves its own validation pass.
