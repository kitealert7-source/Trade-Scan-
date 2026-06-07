# Cointegration Deployment-Universe Policy — Re-evaluation (V2)

**Date:** 2026-06-07
**Supersedes:** `COINTEGRATION_DEPLOYMENT_UNIVERSE_POLICY_2026-06-07.md` (V1) on the central question. V1's structure (two-layer, daily-regime-gated, threshold not Top-N) survives; **V1's pair-centric "thick-record floor" (its Policy D) is refuted by the trade-density measurement below and is replaced by a family-centric construction.**
**Mandate:** Re-derive the deployment-selection policy from the full corpus. Treat *both* the proposed Top-20/15-day policy *and* the V1 report as hypotheses. Decide pair-centric vs family-centric. Trade density is the priority variable.
**Status:** Study + recommendation. **No code, no implementation, no schema/screener change.** Edge findings tagged CONFIRMED (v2 pipeline-stamped) / PROVISIONAL (v1 corpus). Density/regime numbers are read-only and reproducible (`tmp/density_pair_vs_family.py`, `tmp/coint_persistence_funnel.py`).

---

## 0. The one-paragraph answer

**Build the Approved Universe family-centrically, not pair-centrically.** Every per-pair selector the team has tested fails (strength anti-predicts, recurrence is chance, opportunity-set is flat), and the per-pair record is statistically thin (**median 2 regime-episodes/pair**) — so a pair-level edge ranking is mostly noise, and gating on it is actively harmful: it **halves-to-thirds deployment density while filtering on noise**. The stable, broad, pipeline-aligned signal is **structural family** (FX-FX + validated sub-families: JPY-cross×JPY-cross, Antipodean×Antipodean, CHF-anchored), which carries **zero blowups** and **75–93 % positive member pairs**. Measured over the full v2 history, a family-centric universe delivers a **healthy rotating portfolio (~2.7 deployments/day, ~5.9 recently)** versus the **~1/day (often zero, with multi-month dead stretches)** of a Top-20 or elite-pair policy. **Keep N=5 admission and immediate-removal-on-break; drop the Top-N and the pair-edge floor; split the 15-day refresh into a slow structural layer and a daily regime layer.**

---

## 1. Part 1 — Stress-test of the proposed policy

### A. Fixed Approved Universe (e.g. Top-20)
- **For:** simple, bounded, operator-legible; caps capital/correlation exposure by construction.
- **Against:** (1) *Top-N of WHAT?* The only legible ranking is per-pair Ret/DD — which rests on **median 2 episodes/pair** and which **every selector study shows is non-predictive** (strength ρ≈+0.23 *wrong way*; recurrence 4/18 ≈ chance). (2) The append-only ledger ages a fixed cutoff the wrong way (already learned via `all_profitable`→badge). (3) It is **density-starved** (see Part 3): Top-20 averages **1.3 deployable/day, zero on 28 % of days**.
- **Failure mode:** the "best 20 historical pairs" are disproportionately *currently broken* (elite-13: **63 % of days zero deployable, a 315-bar dead streak**) — you optimize the universe for a regime that has passed.
- **Better alternative:** a **self-sizing, structural (family) membership set**, not a ranked Top-N. Cap *deployed* count downstream via correlation-aware allocation if capital-bound — not the *universe* definition.

### B. 15-day refresh cycle
- **For:** batch cadence is operationally easy; edge records don't move daily.
- **Against:** it conflates two clocks. The **regime** clock is *fast* — FX-FX median continuous cointegration life is **9 bars**, only **41 % survive to +15** — so a 15-day-refreshed eligibility list is ~55–60 % stale mid-cycle. The **edge/family-validity** clock is *slow* — 15 days adds almost no new corpus evidence, so re-ranking that often just chases noise.
- **Failure mode:** admissions lag the screener by up to 15 days (miss live opportunities) *and* the universe re-ranks on statistically-insignificant deltas.
- **Better alternative:** **split the cadence.** Family-validity re-evaluation: slow (quarterly / corpus-growth-triggered). Regime eligibility: **daily** (the screener already runs daily; the infra exists).

### C. N=5 admission threshold
- **For / verdict KEEP:** decisively validated. **54 % of all cointegration spans are < 7-bar flickers** that N=5 removes; the decomposition shows N=5 supplies the *return-quality* (median net 0.456 vs 0.130 at N=0) **and** better entry timing, while N=0 yields 14.6 % window-invalid premature entries. **[CONFIRMED]**
- **Against:** none material. N could be tuned (3–7) but 5 = one trading week and matches the screener's hysteresis lag; no evidence to move it.
- **Failure mode (minor):** on a genuinely fast-reverting pair, N=5 delays entry ~5 days — acceptable; the alternative (N=0) admits noise.
- **Better alternative:** keep N=5; treat **p ≤ 0.01 as a *separate* blowup-control knob** (it cuts blowups 3.7 %→0.7 %), not a return driver — they are orthogonal axes.

### D. Immediate removal on break
- **For / verdict KEEP — essential.** Given fast churn, removal-on-break does the real risk work, not the periodic refresh. Operationally trivial (daily screener + offboarding exist).
- **Against:** none. The only refinement: act on **`breaking`**, not just `broken` — `breaking` precedes `broken` ~**85 %** of the time (only 1.1 % of breaks jump straight to broken), giving ~1 bar of early warning.
- **Failure mode:** a 1-bar `cointegrated→broken` jump (1.1 % of transitions) gives no warning — but immediate removal still fires next bar; bounded by the position's own stop.
- **Better alternative:** keep immediate removal; add **`breaking` as a pre-removal "freeze new entries / prepare offboard" state.**

### E. Current-screener + Approved-Universe architecture
- **For / verdict SOUND.** Research → Approved → daily screener → Eligible → deploy → daily recheck → remove is the right control structure, and the infra exists.
- **Against:** only the **content of the "Approved Universe" node** is wrong if it's a pair Top-N. Make that node **structural (family membership + validity tier)**, not a pair ranking.
- **Failure mode:** none architectural; the failure is purely in universe *construction* (Parts 2–3).
- **Better alternative:** keep the architecture; change the Approved node from "Top-N pairs" to "validated-family FX-FX set, proven-bad vetoed."

---

## 2. Part 2 — Universe construction (pair-centric vs family-centric)

**This is the load-bearing decision, and the evidence is one-directional: family-centric wins.**

**Why pair-centric is weak (evidence):**
- Per-pair evidence is thin: **median 2 episodes/pair** (mean 3); only 137/292 pairs have ≥3 regime-episodes. A pair's Ret/DD rank is ~2 regime samples — noise.
- Every per-pair selector tested **failed**: cointegration strength *anti*-predicts edge (ρ≈+0.23), recurrence/sign-persistence is chance (4/18, p=0.51), and within-class opportunity-set features are flat W-vs-L (the 30-bar z-score standardizes pairs). **[PROVISIONAL — v1 corpus, but operator already acted on them]**

**Why family-centric is strong (evidence — corpus pair-grain, v2/GP, `cointegration_sheet`):**

| Family (FX-FX) | pairs | runs | pooled median Ret/DD | % member-pairs positive | blowups |
|---|---|---|---|---|---|
| **JPY-cross × JPY-cross** | 15 | 136 | **0.45** | **93.3 %** | 0 |
| **Antipodean × Antipodean** | 17 | 105 | 0.43 | 88.2 % | 0 |
| **CHF-anchored** (one CHF leg) | 22 | 211 | 0.44 | 81.8 % | 0 |
| USDCHF-hedge (subset of CHF) | 12 | 113 | 0.36 | 75.0 % | 0 |
| JPY-anchored (any JPY leg) | 61 | 462 | 0.28 | 73.8 % | 0 |
| GBP-anchored | 46 | 282 | **0.20** | **58.7 %** | 0 |
| FX-FX (all) | 91 | 663 | 0.29 | 69.2 % | 0 |

- The family signal is **real and broad** — in the strong families **75–93 % of member pairs are individually positive**, not a 1–2-pair artifact. Family aggregates pool 100–460 runs vs a pair's ~6 → far thicker, far more stable than any pair rank.
- **Refinement of the prior reports:** the strongest structure is **structurally-symmetric same-family pairs** (both legs JPY-crosses, both Antipodean) — mechanism = matched sessions / matched risk-on-off legs. **CHF-anchored** is the single-leg exception (CHF = the risk-off hedge). **GBP-anchored is weak (0.20 / 59 %)** — barely above the FX-FX baseline; **do not treat "GBP-cross" as a validated family.** "USDCHF-hedge" is good but is really a subset of the broader, stronger **CHF-anchored** family.
- **Zero blowups in every FX-FX family** → the downside of admitting a thin/unproven family member is *bounded*, which is what makes "admit by structure" safe.

**The decisive current-snapshot test** — of **31** currently-cointegrated FX-FX pairs (N=5-confirmed):
- pair-centric admits (runs≥5 & median Ret/DD≥0.5 & 0 blow): **8**
- family-centric admits (in a validated family): **20**
- both 5 · pair-only 3 · **family-only 15** · neither 8

→ family-centric captures **2.5× more live opportunities**, and the 15 "family-only" pairs are missed *only because their individual record is thin* — exactly the noise axis we shouldn't gate on.

**Answers to the Part-2 questions:**
- *Fixed Top-20?* **No** (Part 1A, Part 3).
- *Fix universe size at all?* **No** — self-sizing structural set.
- *Family diversification matter?* **Yes — it is the primary axis.**
- *Repeat appearances across reports matter?* **Yes, but as family corroboration**, not pair cherry-picking — the same *families* (JPY/CHF/Antipodean) recur across N30, family-density, elite-universe, and class-edge studies. Per-pair repeat-appearance is the recurrence selector that *failed*.
- *Robustness across parameter variants matter?* **Yes, at family grain** (the family pools across sizing/p/N/exit/basis); at pair grain it's the thin axis.
- *Transferability matter?* **Yes, and it argues for family-centric** — edge is window-conditional and does *not* transfer pair→pair, but the *family structure* (symmetric legs) is what transfers. Treat the family as the unit of transfer, the pair as a sample.
- *Deployment density matter?* **Yes — it is co-equal with edge quality** (Part 3).

**Recommendation:** **Approved Universe = family-centric.** Admit any FX-FX pair in a validated family (JPY-cross×JPY-cross, Antipodean×Antipodean, CHF-anchored), **with an asymmetric "proven-bad" veto** (exclude only pairs with episodes ≥ 4 **and** median Ret/DD < 0 — consistently-bad, not merely thin). **No "proven-good" floor** (it filters noise and halves density). Exclude GBP-anchored (weak), all FX-IDX, CRY/MET, FRA40.

---

## 3. Part 3 — Trade-density study (the priority section)

**Method:** for each policy, walk the full v2_log_eg 1D/252 screener history (638 days, 2023-12-29→2026-06-07); a pair is "deployed" on day *d* if it is in a cointegrated run of length ≥ N+1 on *d* (forward-filled across calendar gaps). Universe definitions from the corpus edge record. *(Caveat: universes are defined on today's full record, so this is a relative-density comparison, not an edge claim.)*

| Policy | universe | mean/day | median | %0-days | %≥3 | %≥5 | longest 0-streak | recent mean (252) |
|---|---|---|---|---|---|---|---|---|
| **A** Top-20 (pair edge) | 20 | 1.3 | 1 | 28.2 % | 15.5 % | 1.9 % | 30 | 2.1 |
| **B** Elite-13 | 13 | 0.9 | 0 | **62.9 %** | 15.4 % | 5.0 % | **315** | 2.0 |
| **D** V1-report (FX-FX + thick pair record) | 21 | 1.4 | 0 | 53.1 % | 20.1 % | 11.6 % | 146 | 3.1 |
| **F** Family + thick record | 17 | 1.2 | 0 | 60.5 % | 19.6 % | 8.9 % | 313 | 2.7 |
| **C** Family-centric (validated fams, any record) | 65 | **2.7** | 1 | 48.0 % | 32.8 % | 23.2 % | 97 | **5.9** |
| **E** FX-FX class only (any record) | 91 | 3.8 | 2 | 31.8 % | 44.5 % | 26.6 % | 76 | 7.8 |

**Findings:**
1. **Pair-centric = density-starved.** A/B/D/F all average **≈1 deployable/day** and are *zero* on 28–63 % of days, with multi-month dead stretches (elite-13: **315 bars ≈ 15 months** with nothing deployable). This is precisely the "1 active deployment" failure the mandate flags.
2. **The pair-edge floor is the dominant density destroyer.** Adding it removes ~60 % of deployments for *no reliable edge gain*: E→D drops 3.8→1.4; C→F drops 2.7→1.2. Because the floor filters a 2-episode-thin, non-predictive axis, this is **density spent on noise**.
3. **Family-centric (C) is the edge/density sweet spot:** **2.7/day (5.9 recently)**, a genuine rotating portfolio (≥5 deployable on 23 % of days), while retaining a *validated* structural prior (0 blowups, 75–93 % positive member pairs). Class-only (E) is denser (3.8) but drops the family prior and admits weak structures (e.g. GBP-anchored).
4. **Biggest density bottleneck = the current-cointegration requirement** (intrinsic: 465→77, Part 3 of V1). After that, **the controllable bottleneck is whichever edge filter you stack** — and the data says use the *cheap* one (class+family, −0 density beyond the class gate) not the *expensive* one (pair floor, −60 %).
5. **Operational practicality:** family-centric keeps the deployed set in a manageable band (median 1, p90 8, max 22) — onboard/offboard load is bounded; the daily churn (~9-bar FX-FX life) means steady rotation, not thrash, given N=5 damping.

**Density ranking for "maximize deployable opportunity while preserving edge quality": C (family) ≳ E (class) ≫ A/D/F/B (pair).** C is recommended over E because it keeps the validated family prior at only ~30 % density cost; E is the fallback if more density is ever needed.

---

## 4. Part 4 — Recommended screener view (decision support)

Operators need to separate wheat from chaff on the **structural** axis first, regime axis second, pair-metrics last (as context). Minimum five states:

| State | Definition | Minimum fields to surface |
|---|---|---|
| **Approved Universe** | validated-family FX-FX, proven-bad not vetoed | pair, **family + family-validity tier**, proven-bad flag |
| **Eligible Today** | Approved ∩ cointegrated ∩ N=5-confirmed | + current regime, **days-in-span**, **current z (entry proximity)**, **hedge ratio** (leg sizing), [context: runs/episodes/median Ret/DD] |
| **Active Deployments** | currently live baskets | + entry date, age, live P&L, leg lots |
| **Watchlist** | Approved-family but not yet eligible (`breaking` / sub-N5 / not cointegrated) | + why-waiting reason, days-since-broken |
| **Recently Broken** | was eligible/active; regime just went `breaking`/`broken` | + break date, **span length achieved**, last z, remove-flag |

**Wheat-vs-chaff minimum information (the reframe):**
- **Lead with class + family + family-validity tier** — that *is* the chaff filter (FX-IDX / CRY-MET / FRA40 / GBP-anchored → chaff). Per-pair metrics are **context, not gate.**
- **Entry-readiness = current z** distinguishes "eligible but at the mean (no entry yet)" from "eligible and dislocated (entry live)."
- **Days-in-span + N=5 flag** shows admission status and how mature the regime is.
- **Hedge ratio** surfaced so per-leg beta-ratio lot sizing is one lookup.
- **Reason codes** on Watchlist/Recently-Broken/Rejected — the exclusions are the decision.
- This is an **extension of the existing MPS "COINT TRADE CANDIDATES" tab** (which already carries runs / losses / median Ret/DD / `Coint Status (252d)`), reframed family-first and joined to span-age + current-z. No new subsystem; no implementation in this report.

---

## 5. Part 5 — Final recommended deployment policy

**"If I were designing this today with the full corpus and current ops, exactly this":**

1. **Class gate (hard):** FX-FX only. Exclude FX-IDX, CRY/MET, and any FRA40 combination. *(v2-confirmed: FX-FX 62 % pos, rdd 0.54, 0 blowups; others carry every blowup.)*
2. **Approved Universe = family membership (structural, slow):** admit FX-FX pairs in a **validated family** — JPY-cross×JPY-cross, Antipodean×Antipodean, CHF-anchored (incl. USDCHF-hedge). Exclude GBP-anchored. **Not fixed-size.** Re-evaluate family validity **quarterly / on corpus growth**, not every 15 days.
3. **Proven-bad veto, no proven-good floor:** within approved families, exclude only pairs with episodes ≥ 4 **and** median Ret/DD < 0. Admit thin/unproven members (FX-FX has 0 blowups → bounded downside; family prior covers them). **Do not impose a pair Ret/DD floor** (it halves density for noise).
4. **Daily eligibility (fast):** a pair deploys when it is **currently cointegrated** with an **N=5-confirmed** span (run ≥ N+1). Screener-driven, **daily**.
5. **Immediate removal on break; `breaking` = freeze-new-entries + prepare-offboard** (1-bar early warning, fires ~85 % of the time).
6. **No fixed Top-N; self-sizing.** If capital-constrained, cap the **deployed** set by **correlation-aware allocation** (the validated families share legs — CHF, JPY — so cap correlated exposure), using the candidate-tab sort only as an intra-family tiebreaker.
7. **Sizing/exit/params:** unchanged — granular_parity, zcross, N=30, 1D basis (all validated; the GP_ZCRS reference).

**Expected behavior (measured):** ~**2.7 deployable/day (≈5.9 recently)**, ≥5 deployable on ~23 % of days, longest dead stretch ~97 bars (vs 315 for elite-pairs) — a **healthy rotating FX-FX portfolio**, dominated by the JPY-cross / CHF-hedge / Antipodean families, with bounded (zero-blowup) downside.

---

## 6. Alternatives considered (and why rejected)

| Alternative | Verdict | Reason |
|---|---|---|
| Top-20 by pair edge (proposal) | **Reject** | 1.3/day, 28 % zero-days; ranks a 2-episode noise axis; ages wrong. |
| Elite-13 pairs only | **Reject** | 0.9/day, 63 % zero-days, 315-bar dead streak — optimizes for a passed regime. |
| V1 report: FX-FX + thick pair-record floor | **Reject (self-correction)** | 1.4/day, 53 % zero-days — the pair floor filters noise and starves density. |
| Family + thick pair-record (F) | **Reject** | 1.2/day — the floor undoes the family density gain. |
| FX-FX class only (E) | **Acceptable fallback** | 3.8/day but drops the validated-family prior; admits weak structures (GBP-anchored). |
| **Family-centric, proven-bad veto (C-refined)** | **Adopt** | 2.7/day, validated prior, 0 blowups, 2.5× the current opportunities of pair-centric. |
| Strength / recurrence / persistence ranking | **Reject** | Anti-predictive / chance; the failed-selector arc. |

---

## 7. Open risks & unresolved questions

**Risks**
- **Correlation, not count, is the real exposure cap.** The validated families share legs (CHF, JPY) — 5 simultaneous USDCHF-hedge baskets are nearly one bet. Density without a correlation cap overstates diversification. *Mitigation: allocate on correlation-adjusted count, not raw count.*
- **Proven-bad veto is itself a thin-data call** (it needs episodes ≥ 4); most pairs won't trip it. It removes the few clearly-negative members (e.g. EURUSD/USDCHF, EURAUD/USDCHF) without over-fitting. Monitor that it doesn't grow into a back-door pair floor.
- **GBP-anchored demotion is corpus-current** (0.20 / 59 %); revisit as runs accumulate — it may be a thin-evidence artifact rather than a true weak family.
- **Density universes are defined on today's record** (mild look-ahead in the *comparison*, not the edge); the *relative* ranking (family ≫ pair) is robust to this.
- **Horizon mismatch persists:** 1D/252 cointegration is a *class/structure localizer*, not a 15m edge signal; never read the daily label as an edge claim.

**Open questions (read-only, cheap)**
1. **Promote the failed-selector findings to v2** (strength/recurrence on the 2249-row GP corpus) — the only way to *harden* "don't rank by pair metrics." Highest ROI.
2. **The one selector that could still beat family:** conditional/OOS z-reversion of ±2σ excursions measured in a prior window. If null, "class + family" is the proven ceiling and pair-level refinement is permanently not worth it.
3. **Family taxonomy formalization:** is "structurally-symmetric same-family" (both legs same group) provably better than single-anchor across the v2 corpus? (B suggests yes: JPY-cross-both 0.45 vs JPY-anchored 0.28.)
4. **Correlation structure of the validated families** — measure the live spread-return correlation across USDCHF-hedge / JPY-cross members to set the allocation cap (point-of-risk, not yet quantified).
5. **N-tuning under family-centric:** does N=5 remain optimal when admission is family-gated rather than universe-wide? Likely yes, but unmeasured.

---
*Study deliverable. No code generated, no schema/screener change. Read-only analysis scripts in `tmp/` (`density_pair_vs_family.py`, `coint_persistence_funnel.py`). Recommends a policy + a view reframe; implements neither.*
