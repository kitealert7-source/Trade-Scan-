# Cointegration Deployment Policy — Adversarial Review

**Date:** 2026-06-07
**Mandate:** Independently attack the proposed deployment-selection policy *and* the V2 family-centric report. Overturn if wrong; explain if it survives. Hunt: selection bias, survivorship, density illusion, look-ahead, family over-generalization, hidden concentration.
**Result:** **The V2 "family-centric beats pair-centric" conclusion does NOT survive.** Its two load-bearing pillars — a density advantage and a family edge — are substantially **illusory** (correlation inflation; failed placebo). What survives adversarial attack is narrower and more honest: **the FX-FX class is the only robust edge signal, and effective diversification is ~1–1.4 independent bets under every policy — correlation, not universe size or family choice, is the binding constraint.**
**Status:** Study only. No code/schema/screener change. Measurements read-only, reproducible (`tmp/adversarial_review.py`).

---

## 0. Headline (what the attack proved)

Three independent measurements converge:

1. **The density advantage is a correlation illusion.** Family-centric shows 2.8 raw deployments/day but only **1.1 *effective independent bets*** (leg-sharing inflation **2.6×**); Top-20 shows 1.3 → **1.2 effective**. **On an effective-bet basis, family-centric ≈ pair-centric ≈ class (1.1–1.4) — the "healthier stream" advantage evaporates.** Cointegrated FX-FX pairs hub on a few legs (USDCHF, JPY crosses), so adding pairs adds count, not diversification.
2. **The family edge is mostly a placebo.** Against random FX-FX groupings, only **JPYcross-both is significant (p=0.020)**; CHF-anchored (p=0.116) and Antipodean (p=0.051) are **indistinguishable from random**. The family premium is the FX-FX *class* edge wearing a family costume.
3. **Family-centric trades quality for (illusory) quantity.** Its deployed-stream edge is **0.70 vs Top-20's 1.77**, and it carries 76% JPY-leg / 55% CHF-leg exposure — a **hidden risk-off macro concentration** whose 0-blowup record comes from a single calm 2024–26 window.

**Net:** keep the FX-FX class gate, N=5, and immediate removal; **demote "family" from an edge filter to a correlation-control grouping**; make **correlation-capped allocation** — not universe construction — the primary risk lever.

---

## 1. Part 1 — Attack the conclusions

| Conclusion attacked | Verdict | Why |
|---|---|---|
| **Family-centric selection** | **OVERTURNED as an *edge* claim** | Placebo (M2): only 1 of 3 families beats random FX-FX. Stands only as a *correlation grouping* (M1). |
| **Reject Top-N** | **SURVIVES (but for a new reason)** | Top-N's edge (1.77) is hindsight-selected and it's density-starved (1.3/day, 28% zero-days) — but its *effective* diversification (1.2) is actually the best measured. Reject Top-N as the *sole* mechanism, not because family beats it. |
| **Reject pair-level ranking** | **SURVIVES** | Pair record is thin (median 2 episodes) and its apparent edge is look-ahead. But neither does family ranking help — the honest move is *class*, not pair *or* family ranking. |
| **N=5 admission** | **SURVIVES (as a dial)** | M4: admitted FX-FX spans have median 9 tradeable bars; N=3 vs N=5 is a density/quality lever (50% vs 41% of spans admitted). Keep N=5 default; expose N. |
| **Immediate removal** | **SURVIVES** | Unchallenged; `breaking` gives ~85% pre-warning. |

**Bias audit results:**
- **Density illusion — CONFIRMED PRESENT (M1).** Raw pair-count overstates diversification 2.6× for family-centric.
- **Family over-generalization — CONFIRMED PRESENT (M2).** 2 of 3 "validated" families fail a permutation test vs random FX-FX subsets.
- **Hidden concentration — CONFIRMED PRESENT (M1).** Deployed family stream = 76% JPY-leg, 55% CHF-leg.
- **Survivorship (time) — PLAUSIBLE.** 0 blowups across all FX-FX families is from a benign window; a synchronized risk-off shock (CHF+JPY rally) is unrepresented and would hit most baskets at once.
- **Look-ahead — PRESENT but *conservative*.** Universes defined on full-period record flatter the *pair* policies (hindsight winners) more than the structural family policy — yet pair policies still don't win on effective bets. So look-ahead doesn't rescue pair-centric.
- **Selection bias (corpus) — BENIGN here.** Family edge conditions on "pair cointegrated enough to form episodes" — which matches the deployment condition, so it's the right conditioning.

---

## 2. Part 2 — Universe construction (re-answered after attack)

| Question | Answer | Evidence |
|---|---|---|
| Pair-centric or family-centric? | **Neither as an edge filter — CLASS-centric.** Family only as a correlation bucket. | M2 placebo: families ≈ class. M5: FX-FX class is the stable, real signal. |
| Fixed-size or open? | **Open** (the whole FX-FX cointegrating class). | Fixed-N is hindsight + density-starved (1.3/day). |
| Top-N useful or harmful? | **Harmful as the universe; useful only as an intra-bucket tiebreaker.** | M1/M3: Top-N edge is hindsight; density-starved. |
| Should pair history matter? | **Only as a *veto* on proven-bad, never as a *rank*.** | Thin (2 episodes); apparent edge is look-ahead. |
| Should family history matter? | **For correlation grouping, yes; for edge, only JPYcross-both (weakly).** | M2. |
| Should transferability matter? | **Yes — it argues for class, not pair or family** (edge is window-conditional; only the *class structure* transfers). | prior corpus. |
| Should density matter? | **Raw density: NO (illusion). Effective (correlation-adjusted) density: YES — and it's ~1–1.4 everywhere.** | M1. |

**Recommendation:** the universe is **the FX-FX cointegrating class** (open, structural). "Families" are retained as **correlation buckets** to enforce diversification at deploy time, not as an edge gate. Apply a **proven-bad veto** only.

---

## 3. Part 3 — Deployment density (was it measured correctly? — NO)

**The V2 density measurement counted raw deployable pairs. That is the wrong unit.** Re-measured on effective independent bets (leg-sharing connected components):

| Policy | raw pairs/day | **effective bets/day** | inflation | deployed-stream edge | macro load |
|---|---|---|---|---|---|
| Family-centric | 2.8 | **1.1** | 2.59× | 0.70 | 76% JPY, 55% CHF |
| Top-20 (pair) | 1.3 | **1.2** | 1.14× | 1.77* | 36% JPY, 30% CHF |
| FX-FX class | 3.8 | **1.4** | 2.68× | 0.57 | 68% JPY, 60% CHF |

\*hindsight-inflated (Top-20 selected for edge on the same record).

**Findings:**
- **The density advantage is an artifact of correlation.** Family-centric's 2× raw-count lead over Top-20 *reverses* on effective bets (1.1 vs 1.2). The extra family pairs share hub legs → add count, not independent exposure.
- **Effective diversification is ~1–1.4 under *every* policy.** This is the real, surprising result: **deployment density is a near-non-issue** — you cannot get a meaningfully diversified book of cointegrated FX-FX spreads, because they all route through USDCHF / JPY hubs. The strategy is structurally a **small, concentrated book (~1–2 real bets)** regardless of universe choice.
- **"Healthier deployment stream" — overturned.** A higher *count* of correlated baskets is not a healthier stream; it is leverage on one macro factor.

**Answer:** A family-centric universe does **not** produce a healthier deployment stream. It produces *more, more-correlated, lower-edge* deployments. The apparent advantage was a density illusion.

---

## 4. Part 4 — Screener evolution (decision quality)

Given the real binding constraint is **correlation**, the operator's view must surface *bucket occupancy*, not just opportunity count. Minimum information to separate deployable opportunity from structural noise:

- **Class + cointegration state + N=5 flag + current-z (entry proximity)** — the eligibility core.
- **Correlation bucket + current bucket occupancy** — *the new must-have*: "this pair shares USDCHF with 3 already-deployed baskets." Without this, an operator builds a falsely-diversified book.
- **Macro-factor tag** (risk-off CHF/JPY vs risk-on AUD/NZD) + **portfolio-level factor load** — so the operator sees "you are 76% risk-off right now."
- **Proven-bad veto flag**; pair record (runs/episodes/median Ret/DD) as *context only*.
- **Hedge ratio + days-in-span**; **Recently-Broken** feed for removal.

The "wheat vs chaff" cut is **class (chaff = FX-IDX/CRY-MET/FRA40)** then **bucket-saturation (chaff = the 4th correlated USDCHF basket)** — *not* a family-quality ranking.

---

## 5. Part 5 — Stress-test the (revised) policy

Stressing **"FX-FX class universe + N=5 + immediate removal + correlation-capped allocation"**:

- **Failure mode — synchronized break.** A macro regime shift breaks many FX-FX coint relationships at once → mass simultaneous removal → realize many spreads at the worst moment. *Mitigation:* the equity circuit breaker + per-basket stop; accept that this is a concentrated book.
- **Corner case — bucket starvation.** After correlation caps, the *deployable* book may be 1–2 baskets on many days (effective bets ≈1.1). The policy must not pad to hit a count target. **Accept low count as honest.**
- **Hidden risk — macro beta.** The book is a short-risk-off-vol bet (CHF/JPY mean-reversion). A trending risk-off regime (not mean-reverting) bleeds all baskets together. The 0-blowup history doesn't cover this.
- **Scaling — capital.** With ~1–2 effective bets, capital allocated per bet is the lever, not pair count. Scaling = more capital per bet (concentration) or accepting idle capital, **not** more pairs.
- **Correlation — the core issue.** Even within "diversified" deployment, residual correlation across CHF/JPY spreads is high; the cap must be on *factor exposure*, not pair count.
- **Operational — churn.** 9-bar median life + immediate removal → frequent on/off-boarding; unmodeled transaction/slippage cost on each cycle erodes the thin edge. Needs a realized-cost check before live.

---

## 6. Points of agreement / disagreement

**Agree with proposal & V2:** FX-FX class gate; exclude FX-IDX/CRY-MET/FRA40; N=5 admission; immediate removal; daily regime eligibility; reject fixed Top-N as the universe; structural-over-recent-ranking *instinct*.

**Disagree (overturn):**
- V2's **"family-centric beats pair-centric"** — families are mostly a class-placebo (M2); family ≈ pair on effective bets (M1).
- V2/proposal's framing of **density as a won advantage** — it's a correlation illusion (M3); effective density is ~flat.
- The implicit assumption that **a larger validated universe → a healthier book** — false; the book is ~1–2 effective bets regardless.

---

## 7. Risks & alternative policies considered

**Alternatives:**
| Policy | Verdict |
|---|---|
| Pair Top-N | Reject (hindsight edge, density-starved, but best effective-bet ratio — keep as tiebreaker). |
| Family-centric (V2) | **Reject as edge filter** (placebo); keep families as correlation buckets. |
| FX-FX class + correlation-capped allocation (**revised**) | **Adopt** — honest about ~1–2 effective bets. |
| JPYcross-both-only (the one real family) | Too narrow (density-starved, single-macro); fold into the class+bucket approach. |

**Residual risks:** time-survivorship (calm window → 0 blowups may not hold); unmodeled churn cost on the thin edge; macro-beta concentration; the placebo result is on `median Ret/DD>0` (coarse) and v1-provenance for the selector falsifications (PROVISIONAL).

---

## 8. Final recommendation (after adversarial review)

**The policy that survives attack:**

1. **Universe = the FX-FX cointegrating class** (open, structural). Exclude FX-IDX, CRY/MET, FRA40. *No Top-N, no family edge-gate.* This is the only placebo-surviving, time-stable, v2-confirmed signal.
2. **Proven-bad veto only** (exclude pairs with episodes ≥4 AND median Ret/DD < 0); no pair-edge floor, no edge ranking.
3. **Eligibility = currently cointegrated + N (default 5; expose 3–5 as a density/quality dial).**
4. **Families = correlation buckets, not edge tiers.** Define buckets by shared hub leg / macro factor (USDCHF-hub, JPY-cross, Antipodean, CHF-risk-off, AUD/NZD-risk-on).
5. **Primary risk lever = correlation-capped allocation:** cap simultaneous deployments per bucket and per macro factor (e.g., ≤1–2 per hub leg). Use pair record only as an intra-bucket tiebreaker.
6. **Immediate removal on break; `breaking` = freeze-new + prepare-offboard.**
7. **Size the book for ~1–2 effective bets.** Allocate capital per *bet*, not per pair; do not mistake N deployed pairs for N bets. Explicitly capitalize or hedge the residual risk-off macro beta.
8. **Cadence:** class/bucket definitions reviewed slowly (quarterly); regime eligibility daily.

**The one-line reframe:** *Stop optimizing which pairs/families to admit (the signal there is class-level and the rest is noise); start optimizing how many correlated baskets to run at once — that is where the real, measurable risk lives.*

---

## 9. Open questions
1. **Measure true spread-return correlation** across deployed FX-FX baskets (the leg-component proxy over/under-states it) → calibrate the bucket cap precisely. **Highest priority.**
2. **Realized churn-cost** of immediate-removal at 9-bar median life — does the thin edge survive transaction costs? Run a cost-loaded replay before live.
3. **Stress the macro-beta:** find/construct a risk-off-trend window and check FX-FX basket co-movement (the survivorship gap).
4. **Promote the failed-pair-selector findings to v2** (still PROVISIONAL) and re-run the placebo on pooled medRDD (not just sign).
5. **N-dial calibration** under the class+bucket policy (3 vs 4 vs 5) on density-adjusted edge.

---
*Adversarial deliverable — overturns the V2 family-centric edge claim on measured evidence; retains the FX-FX class gate and reframes risk control around correlation. No code, no screener change. Scripts in `tmp/`.*
