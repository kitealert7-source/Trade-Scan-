# Cointegration Deployment-Universe Selection — Policy Recommendation

**Date:** 2026-06-07
**Scope:** How to construct the *strategic deployable universe* of cointegration pairs for COINTREV_V3 (`pine_ratio_zrev_v1`, granular_parity sizing, zcross exit, 1D/252 basis, 15m execution), and the minimum screener evolution to support it.
**Status:** Study + recommendation only. **No implementation, no code, no schema/screener changes.** Edge findings are tagged CONFIRMED (v2 pipeline-stamped) vs PROVISIONAL (v1 corpus, not rebuilt under v2 — AGENT.md Inv. #10/#31). Regime-dynamics numbers are read-only screener-DB facts (reproducible via `tmp/coint_persistence_funnel.py`).

---

## 0. Executive summary (the headline)

**Do not build a "Top-20 strategic universe refreshed every 15 days." The evidence contradicts both the fixed size and the single 15-day cadence.** Two facts drive this:

1. **The only robust edge predictor is pair CLASS** (FX-FX clean, 0 blowups; FX-IDX and CRY/MET hostile). Every *continuous* selector the team tested — cointegration strength, recurrence/persistence, opportunity-set features — **failed or anti-predicted**. So a universe must be built on *structural class + thick historical record*, not on a strength/persistence ranking.
2. **A "cointegrated" label is short-lived.** For FX-FX, the median continuous cointegration life is **9 trading bars** and only **41% of pairs survive cointegrated to +15 bars**. The universe churns *faster than the proposed 15-day refresh* — so a periodic fixed-N snapshot is ~55–60% stale by mid-cycle.

**Recommended structure — a two-layer universe, not one list:**

- **Layer 1 — Approved Set (slow, edge-quality, threshold-based):** pairs in the deployable class (FX-FX; IDX-IDX as a probationary 2nd tier) with a *thick* validated record (runs ≥ 5, median Ret/DD above a floor, 0/low blowups, low loss-rate), ideally in a validated sub-family (USDCHF-hedge / JPY-cross / GBP-cross). Re-rank every ~15 days **or** on new-run completion — fine, because edge records change slowly. **Not fixed-size.**
- **Layer 2 — Eligible-Now (fast, regime-gated, daily):** Approved-Set pairs that are *currently* cointegrated with an **N=5-confirmed** span, gated on the **daily** screener. **Immediate removal on break**; the `breaking` state is a 1-bar early warning (fires before `broken` ~85% of the time).

**The candidate policy's core error is conflating these two layers into one 15-day universe.** Keep N=5 (validated noise filter) and immediate-removal-on-break (essential, given fast churn). Split the cadence: edge re-ranking slow, regime eligibility daily.

**Minimum screener evolution:** *extend the existing MPS "COINT TRADE CANDIDATES" tab* into a 4-state decision view (**Eligible / Watchlist / Reject / Recently-Broken**) by joining its edge-quality columns (already present) with the daily regime, span-age, current-z (entry proximity), and hedge-ratio. This is an extension of an existing surface, not a new subsystem.

---

## 1. Q1 — Most defensible process for constructing the strategic universe

**Recommended pipeline (apply in this order; each stage's rationale is evidence-cited in §6):**

| # | Gate | Rule | Why (evidence) |
|---|---|---|---|
| 1 | **Class** (structural) | Keep **FX-FX**; **IDX-IDX** probationary; **hard-exclude FX-IDX & CRY/MET** | Only pipeline-confirmed edge axis: FX-FX 62%pos/rdd 0.54/**0 blowups** vs FX-IDX 50%/0.28/8, CRY/MET 46%/0.52/11 (v2 n=473). CRY/MET cointegration math is also *contaminated* (β≈0, cross-scale). |
| 2 | **Thick record** (edge quality) | runs ≥ 5; median Ret/DD ≥ floor; blowups = 0 (FX-FX) / ≤ tolerance; low loss-rate | Single-window backtests are false-positive-prone (0/18 governance pass; trend-contamination). Edge conviction lives in *pooled-thick* per-pair history. Rank by **Ret/DD**, never net%. |
| 3 | **Sub-family prior** (conviction overlay, not a hard gate) | Flag USDCHF-hedge / JPY-cross / GBP-cross membership | Validated "elite FX-FX" tier is robust across sizing/p/N/exit/basis. Overlay, because shared legs ⇒ correlated if traded jointly. |
| 4 | **Currently cointegrated + N=5** (precondition for a live entry) | latest regime = `cointegrated`, `history_depth ≥ 5`, trailing run ≥ N+2 | The strategy needs a defined, look-ahead-safe entry inside a current span. N=5 confirmation supplies return-quality + entry timing and removes the 54% of spans that are < 7-bar flickers. |

**Layers 1–3 define the slow "Approved Set"; layer 4 is the daily "Eligible-Now" gate.** Promotion to Eligible requires all four; demotion is immediate on a regime break (layer 4 flips daily).

**Explicitly do NOT select on:** cointegration *strength* (anti-predictive), *recurrence/persistence-of-relationship* (no sign-persistence), or *span length* ("methodological cleanliness, never edge"). See Q2.

---

## 2. Q2 — Metrics that distinguish durable edge from noise

### Predictive — USE these
- **Pair class** — the dominant, *pipeline-confirmed* axis (v2 n=473). FX-FX is the only zero-blowup class. **[CONFIRMED]**
- **Pooled-thick per-pair record:** median **Ret/DD**, %positive, runs, blowup count, loss-rate — meaningful *because* thick (the candidate-tab metrics). Rank: loss-rate ↑ → median Ret/DD ↓ → runs ↓. **[CONFIRMED — these are the existing candidate-tab gate]**
- **Sub-family membership** (USDCHF-hedge etc.) — pooled-thick, robust across configs. **[CONFIRMED-ish: decision-grade pooled analysis]**
- **N=5 confirmation** — drives return-quality (median net 0.456 vs 0.130 at N=0) and entry timing; **[CONFIRMED]**. **p ≤ 0.01** is a *blowup* control (0.7% vs 3.7%), not a return driver — keep them as separate knobs.

### Misleading / weak — DO NOT use
- **Cointegration strength (ADF/EG p-value):** *anti-predictive* — Spearman(strength, Ret/DD) ≈ **+0.23**, p<0.001 (lower p / stronger coint → *worse* trading). It is a class-proxy pointing the wrong way (strong coint concentrates in toxic FX-IDX). **[PROVISIONAL — v1 corpus]**
- **Recurrence / persistence of the relationship:** sign does not persist across episodes (all-same-sign 4/18 vs 4.1 expected, p=0.51); peak single-episode edge *anti*-correlates with persistence; recurrence often = decay. A "persistent-relationship watchlist" is not a selection mechanism. **[PROVISIONAL — v1 corpus]**
- **Single-window Ret/DD:** false-positive-prone (0/18 pairs reached a governance verdict on a clean single window; apparent winners often rode a *pre-cointegration trend*, e.g. CHFJPY/UK100 +129% unfiltered → −50% on the actual coint window). Use only as a *fidelity/sanity* check. **[CONFIRMED]**
- **Span length as edge** — never; methodological cleanliness only. Worse, durable spans concentrate in the *hostile* class (see Q5). **[CONFIRMED]**
- **Headline net%** and **single-pair %positive on the episode axis** (1–4 episodes/pair → regime-luck).

**Why every fine-grained selector fails (the mechanism):** the strategy's 30-bar rolling z-score *standardizes away* cross-pair differences — it enters at |z|≥2 on every clean pair, so opportunity-set features (excursions/day, p95|z|, ratio-vol) are flat W-vs-L within the clean class. The only differentiator is whether an excursion *reverts vs follows-through* — small, regime-driven, not predictable from pair statics. **[PROVISIONAL]** This is the deep reason to select on *class + thick track-record*, not on per-pair micro-metrics.

---

## 3. Q3 — Trade-density / funnel impact of the filtering chain

**Current snapshot funnel (v2_log_eg, 1D/252, per-pair latest as-of; full output in §6):**

| Stage | Pairs | Cut vs prior |
|---|---|---|
| Universe (v2) | **465** | — |
| Currently cointegrated | **77** | **−83.4%** ← dominant reducer |
| & N=5-confirmed (history_depth≥5, trailing run ≥7) | **68** | −11.7% |
| & FX-FX (deployable class) | **31** | **−54.4%** ← 2nd reducer |
| & USDCHF-hedge sub-family | **9** | −71% |

- **Dominant reducer = the current-cointegration requirement (−83%)** — but this is *intrinsic*, not a policy choice (you can only trade what is cointegrated now).
- **Largest controllable/policy reducer = the FX-FX class gate (−54%)** of the surviving set. This is the right place for it: it removes the hostile classes that carry all the blowups.
- **Persistence (N=5) is a *small* reducer on today's pair count (−12%) but a *large* quality filter on the time axis:** it removes **54.2% of all spans** (the < 7-bar flickers). So N=5 buys a lot of noise-rejection for little count-loss — high-value, low-cost.
- **Per-pair trade density is not the constraint** — always-in-market 2σ ≈ 2.8 trades/day and ~100 cycles/episode; each deployed pair is active. **The binding constraint is the NUMBER of qualifying pairs (~9–31 today), not trades-per-pair.**
- **Class-class mix of the 68 N=5-confirmed current pairs:** FX-FX 31 / FX-IDX 23 / CRY-MET 12 / IDX-IDX 2 — note FX-IDX and CRY/MET together (35) would *dominate* a naïve "currently cointegrated" list, which is exactly why the class gate is load-bearing.

---

## 4. Q4 — How the screener should evolve ("wheat from chaff")

**Recommendation: extend the existing MPS "COINT TRADE CANDIDATES" tab into a 4-state deployment decision view.** It already carries the edge-quality axis (Pair, Runs, Losses, Median Ret/DD, all_profitable badge) and a current `Coint Status (252d)` regime column. The gap is that it does not *fuse* edge-quality with live-regime + entry-readiness into an operator decision state. The four states an operator needs:

| State | Definition | What to surface |
|---|---|---|
| **ELIGIBLE NOW** | Approved Set ∩ currently cointegrated ∩ N=5-confirmed | pair, class, sub-family flag, **current z (entry proximity)**, **days-in-span**, history_depth, **hedge ratio** (for leg sizing), median Ret/DD, %pos, runs, blowups, loss-rate |
| **WATCHLIST** | Edge-validated + in-class but **not** currently eligible (not cointegrated / `breaking` / span < N+2) **OR** currently cointegrated but **thin** (runs < 5) | same columns + *why-waiting* reason (regime vs evidence) + days-since-broken |
| **REJECT** | Wrong class (FX-IDX/CRY-MET) **or** edge-invalidated (neg median Ret/DD, blowups, high loss-rate) **or** strength-only (no tradeable record) | the **reason code** (the most important field — makes the exclusion auditable) |
| **RECENTLY BROKEN** | Was Eligible/deployed; regime just went `breaking`/`broken` | break date, **span length it achieved**, last z, "remove from deployment" flag |

**Design principles (decision-support, not implementation):**
- **Two axes, always joined:** edge-quality (slow, pooled-thick history) × current-regime (fast, daily). Neither alone decides; the view's value is the join.
- **Reason codes on REJECT/WATCHLIST** — an operator must see *why* a pair is excluded (class? evidence? regime?), because the exclusions are the whole point.
- **Entry-readiness (current z)** distinguishes "eligible but at the mean (no entry yet)" from "eligible and at a 2σ dislocation (entry live)."
- **Hedge ratio surfaced** so per-leg lot sizing in beta ratio is one lookup (live-deployment need).
- **`breaking` as the early-warning lane** — it precedes `broken` ~85% of the time, giving ~1 bar to pre-stage a removal.

This is an *evolution of one existing tab*, not a new screener. No math change, no new methodology.

---

## 5. Q5 — Is a fixed-size universe (Top-20) justified?

**No.** Three independent reasons:

1. **Churn beats the cadence.** FX-FX median continuous coint life = **9 bars**; survival to +15 bars = **41%**. A Top-20 admitted every 15 days is majority-stale by mid-cycle; *immediate-removal-on-break*, not the periodic refresh, is doing the real work. So the regime layer must be **daily**, not 15-day.
2. **The qualifying count is variable and often < 20.** Today only **9** USDCHF-hedge / **31** FX-FX pairs are both eligible-now and in-class. A fixed-20 list would either **pad with sub-threshold pairs** (when few qualify — admitting junk) or **truncate good pairs** (when many qualify). A **threshold** (class + edge floor + current-coint) self-sizes correctly.
3. **The append-only ledger ages a fixed cutoff the wrong way** — the team already learned this with `all_profitable` (demoted from gate to badge) and chose a **graduate-in `runs ≥ 5` gate** over a Top-N row cutoff for exactly this reason.

**Recommended structure instead:** *threshold-gated, self-sizing, two-layer, daily-regime-gated.* If a hard cap is ever needed (capital/correlation limits), apply it **as a downstream allocation constraint on the Eligible-Now set**, ranked by the candidate-tab sort — not as the universe-definition mechanism. And cap on **correlation-adjusted** count, since the elite sub-families share legs (USDCHF, JPY).

---

## 6. Supporting evidence (provenance)

**Pipeline-confirmed v2 class table (cointegration_aggregator, n=473, `methodology_version='v2_log_eg'`):** FX-FX n=127 62%pos rdd 0.54 **blowup 0**; IDX-IDX n=56 43%pos rdd 0.50 blowup 1; FX-IDX n=218 50%pos rdd 0.28 blowup 8; CRY/MET n=72 46%pos rdd 0.52 blowup 11. **[CONFIRMED]**

**Regime dynamics (read-only, current v2_log_eg 1D/252; `tmp/coint_persistence_funnel.py`):**
- *Span duration (1085 spans):* ALL median 5, mean 12.6, ≥7: 45.8%, ≥15: 24.7%, ≥30: 12.2%; **flicker (< 7 bars) = 54.2%.** By class: FX-IDX most durable (median 7, ≥30: 15.9%); FX-FX shorter (median 5, ≥30: 7.4%).
- *Survival P(continuously coint → +k | coint at T):* ALL +5/+10/+15/+30 = 73/57/46/25%; **FX-FX = 70/53/41/19%, forward-life median 9 bars**; FX-IDX = 76/60/50/29%, median 13.
- *Transitions from a coint bar:* → coint 92.6%, → breaking 6.3%, → broken 1.1% (only **1.1%** break straight to `broken`; **~85%** of exits pass through `breaking` first).
- *Funnel:* 465 → 77 (−83%) → 68 (−12%) → 31 FX-FX (−54%) → 9 USDCHF-hedge.

**Selector falsification (v1 corpus — `project_cointegration_methodology_audit`, `_durability_filter_test`):** strength Spearman ρ≈+0.23 (anti-predictive); recurrence sign-persistence 4/18 (p=0.51); within-FX-FX opportunity-set features flat W-vs-L. **[PROVISIONAL — v1, not rebuilt under v2; operator chose no rebuild: confirmatory clean screen → empty corpus.]**

**N=5 / p≤0.01 decomposition (canonical pipeline, 2026-06-02, run_ids a4b28edf…, 22d64647…):** N=5 median net 0.456 vs N=0 0.130; p≤0.01 blowup 0.7% vs 3.7%; N=0 also 14.6% window-invalid premature entries. **[CONFIRMED]**

**Single-window false-positive risk:** PINE_N30_ALIGNMENT_WINDOW (0/18 governance), S21_TRANSFERABILITY (window-conditional, CHFJPY/UK100 +129%→−50% on the coint window). **[CONFIRMED]**

**Elite FX-FX universe (4H_BASIS_EXIT…, decision-grade):** 13 pairs robust across configs; currently cointegrated + tradeable: **CADJPY/USDCHF (+1.21, 87%)**, AUDNZD/USDCHF (+0.77), EURAUD/GBPAUD (+0.77).

**Span survey (2026-05-28, `coint_span_survey`):** durable cointegration concentrates in index-crosses / index×JPY-CHF — i.e. the hostile class; "span-validity = methodological cleanliness, never edge."

**Settled config (FROZEN):** granular_parity sizing (capital-efficiency, parity risk-adjusted on the deployable subset); Z=0/zcross exit dominates baseline (rdd +0.48 vs +0.42, ~2× less tail); both already in the reference variant.

---

## 7. Competing alternatives considered

| Alternative | Verdict | Reason |
|---|---|---|
| **Top-20, 15-day refresh (candidate policy)** | **Reject as stated** | Churn > cadence (FX-FX 41% survive to +15); fixed-N pads/truncates; ledger ages cutoffs wrong. Salvage the parts: keep N=5 + immediate-removal; split cadence. |
| **Rank by cointegration strength (most-cointegrated)** | **Reject** | Anti-predictive (ρ≈+0.23); selects the toxic FX-IDX class. |
| **Persistent-relationship watchlist (recurrence)** | **Reject** | No sign-persistence (4/18); peak edge anti-correlates with persistence. |
| **Persistence/durability as the primary admission axis** | **Reject** | Durable cointegration concentrates in the *hostile* class; persistence ⟂ edge. Use persistence only as the N=5 *entry-confirmation*, not a quality rank. |
| **Single-window backtest per current pair as the gate** | **Reject as a gate** | 0/18 governance; trend-contamination. Keep as a fidelity check only. |
| **All-FX-FX, no edge floor** | **Partial** | Class is necessary but not sufficient — within FX-FX, thick Ret/DD record still separates deployable from marginal. |
| **Two-layer, threshold, daily-regime-gated (recommended)** | **Adopt** | Matches all evidence: class-first, thick-record, daily churn, self-sizing. |

---

## 8. Risks & open questions

**Risks**
- **Small Eligible-Now set (≈9 USDCHF-hedge today)** → concentration. The elite sub-families share legs (USDCHF, JPY) → correlated exposure if traded jointly. *Mitigation:* correlation-aware allocation cap downstream, not a bigger universe.
- **Provisional core.** The "strength anti-predicts" and "recurrence-null" findings are v1-corpus PROVISIONAL. They are *direction-setters the operator already acted on*, but not v2-confirmed. The **class** finding (the load-bearing one) **is** v2-confirmed.
- **In-sample β + in-sample z, no OOS split** in the screener; backtesting a current open span (ending today) is the closest thing to OOS and should be treated as a *fidelity* check, not a fresh edge proof.
- **15m-vs-1D-daily horizon mismatch** — the screen tests 1D/252 cointegration but the strategy trades a 30-bar/15m z-score; cointegration is a *necessary precondition / class localizer*, not a sufficient edge signal. Don't over-trust the daily label as an edge claim.

**Open questions (research, not blocking — all read-only / cheap)**
1. **Re-measure strength-vs-edge and recurrence on the v2 corpus** to promote the PROVISIONAL findings (or refute them) — the only way to harden the "don't rank by strength" rule.
2. **The decisive untested feature:** conditional/OOS z-reversion (of ±2σ excursions, fraction returning to 0 within N bars, measured in a *prior* window) — the one selector that *could* beat class. If it too is null, FX-FX edge is small + regime-driven and *not finely selectable* (which caps any universe-refinement's value and validates "class + thick record" as the ceiling).
3. **Edge-quality floor calibration:** what median Ret/DD / max loss-rate / blowup tolerance defines the Approved Set? Derive from the candidate-tab distribution, don't guess.
4. **IDX-IDX probation:** v2 dropped it to 43%pos (stricter hysteresis). Keep as a 2nd tier with a tighter floor, or exclude? Needs a v2 IDX-IDX thick-record read.
5. **Refresh cadence for Layer 1:** event-driven (on new-run completion) vs fixed 15-day — measure how fast the *edge ranking* (not the regime) actually moves before committing a number.

---
*Study deliverable — no code generated, screener unmodified. Analysis scripts (read-only) parked in `tmp/`. Recommends a structure + a decision-view extension; does not implement either.*
