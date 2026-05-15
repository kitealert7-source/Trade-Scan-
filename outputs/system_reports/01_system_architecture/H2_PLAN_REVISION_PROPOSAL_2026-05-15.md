# H2 Engine Promotion Plan — Revision Proposal v11 → v12

**Status:** PROPOSAL (not yet approved). Per Invariant #11, plan modifications require explicit human re-approval. This doc lays out the proposed change for Monday's decision.

**Date:** 2026-05-15

**Trigger:** operator critique 2026-05-15 — "we are stretching test time so much … we are testing code only and not strategy performance".

**Scope:** Phase Map sections covering 7b → 8 → 8.5 multi-week observation gates. Specifically the architectural commitment "Phase 7a → 7b → 8 trust progression — validator earns trust over ≥14-day observation windows at each stage before gating execution" (plan v11 §"Key architectural commitments" #8).

---

## 1. What is being proposed

Compress the plan's `7b shadow-read (≥14d) → 8 gated mode (≥14d) → 8.5 broker cross-check (≥14d) → 10 LIVE` sequence (~6+ weeks calendar) into a single integration-correctness gate (~1 week calendar) **for the H2 basket strategy specifically**.

**What replaces the multi-week gates:**
1. A focused 24-hour signal-correctness test against live MT5 ticks with `paper_trading=true`. Pass criterion: every recycle/harvest/freeze event mathematically correct against expected formula. Binary, deterministic, bounded.
2. Small-stake live deployment ($1k starting equity per the H2 spec) — the recycle rule's $2k harvest target is itself a self-limiting circuit-breaker (~100% gain cap; worst case loses the $1k stake).
3. Operator monitoring of the first complete harvest cycle as the live-integration confirmation.

**What is preserved unchanged:**
- All Phase 0a–7a work (frozen ABI, basket runner, recycle rules, validator, frozen corpus, full 5-stage acceptance battery)
- Validator code paths + observability (decision file protocol, heartbeat, atomic writes)
- Section 1m / 1m-i frozen corpus immutability invariants
- Section 1l ABI manifest + triple-gate CI
- All other strategies (PINBAR, KALFLIP, RSIAVG, IMPULSE, etc.) continue under the original 7b/8/8.5 gating sequence — this proposal scopes only to H2

**Does NOT change:**
- The plan's *commitment* to a validator → executor gating architecture
- The plan's *intent* to use the validator as a safety layer
- The trust-progression discipline for per-symbol strategies (where the validator's per-signal model is the natural fit)

---

## 2. Why the original gates' rationale no longer applies — for H2 specifically

The plan's 7b/8/8.5 sequence was forged from the prior burn-in regime's failure modes (plan §1n, §1h "burn-in entanglement"). At the time:
- Validator and executor were entangled inside TS_Execution
- No way to isolate "validator code correct?" from "strategy performance?" — they had to be tested together
- Multi-week observation was the only way to gain confidence

**Three things have changed since the plan was written:**

### 2a. Validator code correctness is now independently proven
Phase 7a's 5-stage acceptance battery (commits TSSV `e16a268` → `dcf0dc1`, see `PHASE_7A_PROGRESS_AUDIT.md`) gave us property-level evidence that no number of observation days can match:
- **Stage 1 (port-regression):** byte-identical classification of 7,722 SIGNAL events vs the proven 33-day production reference. SHA-256 `c1f5dd7d…`.
- **Stage 2 (sustained-throughput, 1h):** zero RSS growth, zero handle leak, validator_exit_code 0, throughput ~52k events/sec sustained = ~190M events processed.
- **Stage 3 (adversarial fail-closed, 26 tests):** atomic-write retry under WinError 5, cleanup-on-init, hash determinism, kill-switch stickiness, process-kill recovery, Tier-2 success path.
- **Stage 4 (runtime determinism, 5 tests):** same inputs → byte-identical decision state across consecutive runs + triple-run convergence.
- **Stage 5 (72h field stress, in flight 2026-05-15→18):** OS-level survival under Task Scheduler with realistic disruption.

Per-property evidence is *stronger* than wall-clock evidence. 14 days of "nothing happened" tells you the validator didn't crash in 14 days; doesn't tell you why. Stage 3's 26 fail-closed tests tell you exactly which failure modes are caught and how.

### 2b. H2 strategy correctness is independently proven
- Research 10/10 historical 2-year window survival, +62.8% mean (`memory/project_usd_basket_recycle_research.md`)
- Pipeline → research baseline byte-equivalent on 10-window matrix (Trade_Scan commit `5528ff1`): 5/10 TARGET, 0/10 BLOWN — IDENTICAL to research
- Multiple per-window basket_sim cross-check (Trade_Scan commit `2414e60`)

### 2c. H2's safety logic is INSIDE the strategy, not in the validator
The plan's validator-gating model fits **per-symbol strategies**: each live signal is compared to a research-baseline trade log, and the validator decides ENABLE/DISABLE. Phase 7a's testing exercised this model on the prior portfolio's per-symbol strategies (PINBAR, KALFLIP, RSIAVG, IMPULSE — what the shadow journal recorded).

**H2 is architecturally different.** Its safety logic is *inside* the recycle rule:
- **Equity-floor freeze** (DD ≥ 10% of equity) — built into `H2RecycleRule._check_freezes`
- **Margin freeze** (margin used ≥ 15% of equity) — same
- **Regime gate** (compression < 10) — same
- **Harvest target** ($2k equity → close all + stop) — same
- **Per-leg lot caps** — implicit in the lot math

These freezes execute on every bar inside `basket_pipeline`, not via an external validator decision. The validator's role for H2 is ancillary at best (e.g., "is the corpus that produced the recycle thresholds still valid?"). Forcing H2 through a validator-gated 7b/8/8.5 sequence applies a safety model that doesn't match H2's architecture.

**Bottom line:** the validator-gated trust-progression earns its keep on per-symbol strategies. For H2 the relevant safety layer is the recycle rule itself, which has *already* been tested across 10 historical 2-year windows in research. There is no analogous integration to gain trust in via 6+ weeks of observation.

---

## 3. What changes (the actual revision text)

Plan v12 would modify §"Phase Map" and §"Key architectural commitments":

### §Phase Map — addition

> **H2-specific lane (added v12, 2026-05-15):** The H2 EUR+JPY basket strategy follows a compressed sequence to live, justified by the architectural distinction in §1n-NEW (H2 safety logic is intra-strategy). The standard `7b → 8 → 8.5` gating sequence still applies to per-symbol strategies (PINBAR, KALFLIP, RSIAVG, IMPULSE, etc.).
>
> ```
> Phase 7a       TS_SignalValidator MVP                         [DONE 2026-05-14]
> Phase 7a-H2    H2 live integration build                      [NEW]
>                  - Build basket_pipeline live MT5 adapter
>                  - Build TS_Execution H2 shim
>                  - paper_trading=true 24h signal-correctness test
> Phase 7a-H2-LIVE  $1k stake live, monitor first harvest cycle  [NEW]
> Phase 7b/8/8.5  Per-symbol trust-progression                   [unchanged]
> Phase 9         Matrix extension                               [unchanged]
> Phase 10        Multi-symbol LIVE deployment                   [unchanged - DEFERRED]
> ```

### §"Key architectural commitments" #8 — refinement

> **8. Trust-progression discipline (refined v12):**
> - **Per-symbol strategies** (signal-vs-research-baseline gating model): validator earns trust over ≥14-day observation windows at each of 7b/8/8.5 before gating execution. *(unchanged)*
> - **H2 basket strategy** (intra-strategy safety logic — recycle rule's freezes + harvest target): live integration validated via 24h signal-correctness test + small-stake live monitoring. The recycle rule's $2k harvest target is its own circuit-breaker.
> *Rationale: §1n-NEW.*

### §1n — new subsection

> **§1n-NEW. H2 vs per-symbol architectural distinction (added v12).**
>
> The plan's validator-gated trust-progression assumes a per-signal model: live signal → validator compares to research baseline → ENABLE/DISABLE. This fits per-symbol strategies whose safety reduces to "is this signal in the proven distribution?".
>
> H2 is a basket-with-recycle strategy whose safety logic is *inside* the strategy:
> - DD freeze (10% of equity)
> - Margin freeze (15%)
> - Regime gate (compression ≥ 10)
> - Harvest target ($2k → close all + stop)
> - Per-leg lot caps
>
> These execute on every bar inside `basket_pipeline`, not via external validator gating. Per-symbol multi-week observation gates earn no marginal safety for H2. Compressed sequence acceptable; per-symbol sequence preserved.
>
> **Caveat:** when other basket strategies appear (90_PORT_*), they inherit the H2-lane sequence *only if* their safety logic is similarly intra-strategy. Validator-gating model resumes for any basket whose safety lives outside the strategy.

---

## 4. Risk delta (what this trade gives up vs gains)

### What the original gates gave us — and what we lose by skipping
| Concern | 14d observation catches | Compressed path covers? |
|---|---|---|
| Validator code crashes over time | ✅ catches slow-leak, calendar-pattern bugs | ✅ Stage 2 1h + Stage 5 72h + property-level Stage 3 give equivalent evidence |
| Validator doesn't FAIL-CLOSED on integrity violation | ✅ would surface in 14d if a corpus drift snuck in | ✅ Stage 3's corpus-corruption test + pre-commit corpus_audit hook |
| Decision file readers (TS_Execution) handle stale decisions | ⚠ multi-week observation of reader behavior | ⚠ NOT covered for H2 because H2 doesn't use the validator's decision file (uses basket_pipeline actions) — irrelevant for H2-lane |
| Validator's per-signal classifications track strategy reality | ✅ in 14d you'd see if classifications drift wrong | ⚠ NOT directly — but H2's safety isn't validator-gated, so this doesn't matter for H2-lane |
| **Live integration plumbing (live MT5 → signals → orders)** | ⚠ multi-week is overkill for this; 24h focused test does it better | ✅ 24h dry_run test, deterministic pass criteria |

### What we gain
- 5–6 weeks of calendar time
- Live empirical feedback on H2 mechanics 5–6 weeks sooner
- Less operational fatigue (each multi-week gate has setup friction)

### Financial risk delta
The H2 spec is $1k stake, $2k harvest target.
- Worst-case loss: $1k (entire stake — the strategy's own DD/margin freezes prevent further drawdown beyond floor)
- Best-case gain: $1k harvest then auto-stop (per recycle rule design)
- This is the *smallest* possible live trial of H2 that exercises the full mechanic. Both bounds are operator-tolerable.

### What is NOT given up
- Phase 7b/8/8.5 sequencing for per-symbol strategies. The original validator-gated trust-progression remains the right model for them.
- Phase 10 framing as a separate gate. "Multi-symbol TS_Execution upgrade is the gate" still binding for the broader portfolio. H2 alone goes live via the H2-lane; broader Phase 10 still requires TS_Execution to support multi-symbol/basket dispatch generally.
- Phase 8.5 (broker data cross-check) as a *future* refinement. Useful but doesn't gate H2-live.

---

## 5. Alternative considered and rejected

**Alternative: keep the plan as written, run all gates.**
Rejected for the H2 case because the gates are testing things that are either (a) already proven independently (validator code, strategy performance) or (b) not relevant to H2's architecture (validator-as-gate model). Multi-week observation that adds no marginal information is operational waste.

**Alternative: skip ALL gates including 24h test, go straight live.**
Rejected because the live integration plumbing IS unproven and IS a real risk surface (live tick → signal → order chain). 24h dry_run is small enough to be worth the cost; bypassing entirely would be reckless.

---

## 6. Approval ask

If you approve this revision Monday, the following work happens:

1. I edit `H2_ENGINE_PROMOTION_PLAN.md` to v12 with §Phase Map, §"Key architectural commitments" #8, §1n-NEW changes (~50 lines).
2. Memory file `project_h2_engine_promotion_plan.md` revised to v12 banner.
3. Companion execution plan `H2_LIVE_EXECUTION_PLAN.md` (drafted alongside this proposal) becomes the worklist.
4. Original v11 plan archived to `outputs/system_reports/01_system_architecture/archive/H2_ENGINE_PROMOTION_PLAN_v11_2026-05-13.md` for audit trail.

**If you reject** the proposal, no plan changes happen. The H2-live path proceeds via the original 7b/8/8.5 sequence (~6+ weeks). The drafted execution plan would be discarded.

**If you partially approve** (e.g., approve the architectural distinction but want a 7-day live-shadow gate before flipping to real money), I revise both docs accordingly.

---

*Proposal written 2026-05-15 during Stage 5 weekend run. Read-only doc; no operational state touched. Companion: `H2_LIVE_EXECUTION_PLAN.md`.*
