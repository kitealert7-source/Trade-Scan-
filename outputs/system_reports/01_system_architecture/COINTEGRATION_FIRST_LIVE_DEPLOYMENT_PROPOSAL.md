# Cointegration -- First Live Deployment (Design Proposal)

**Status:** BASELINE (execution architecture) -- 2026-06-03. Every major execution assumption was challenged once via Reviews #1-#5; none collapsed. Remaining work = refinement + implementation planning, not architectural discovery. Still pre-implementation (no code); not locked governance.
**Date:** 2026-06-03
**Author context:** post-stand-down, post-validator-retirement.

**Supersedes / does not reuse:**
- Validator-gated live path (H2 Phases 7b/8/8.5) -- RETIRED 2026-06-03.
- `H2_LIVE_EXECUTION_PLAN.md` -- its **file-bridge pattern is retained** (see decision 1); its validator + continuous-recycle specifics do not apply and are re-derived, not reused wholesale.

**Scope:** take exactly ONE research-approved cointegration basket from PIPELINE_COMPLETE to live, on fixed min lots, for the purpose of **validating live multi-leg infrastructure**. Returns are explicitly NOT the goal of the first deployment.

---

## Guiding principle (reduce first, then layer)

Build the **minimal deterministic core (V0)** that can trade a 2-leg basket live, shaped so the increments that will certainly follow -- sizing, recycle, more baskets, limit orders, automated fidelity -- **bolt onto named seams without a redesign.** Prefer determinism over sophistication. Strategy *quality* is research's job; live execution only verifies *fidelity* (was the promoted signal executed faithfully).

---

## Design convergence principle

The load-bearing principle that emerged from Reviews #1-#5: **when a new failure mode appears, first try to express it with a mechanism that already exists --**

1. **Reconciliation to broker truth** (the target-reconcile loop),
2. **Watchdog recovery** (process supervision / restart),
3. **Circuit-breaker protection** (equity-triggered capital guard).

**Only introduce a new mechanism if the existing three cannot represent the failure mode.** Each review began with an apparent new special case (orphan handling, restart, runner-death) and each reduced to one of the above -- evidence the abstraction is converging. Default posture: *remove a mechanism, don't add one.*

---

## Two architectural decisions

1. **Execution architecture -- current preference: retain the file-bridge.** Not "drop the bridge," not "bridge is mandatory." The basket mechanic runs on the Trade_Scan side (`basket_runner`/`basket_pipeline`) and emits actions consumed by a thin TS_Execution shim, rather than running basket logic in-process.
   **Rationale:** expected future reuse across cointegration, recycle, and future basket mechanics -- plus keeping TS_Execution's only *governed* Trade_Scan dependency as `engine_abi` -- outweighs the additional complexity for the first deployment.
   **This choice is based on anticipated architectural longevity, not on the requirements of the first cointegration deployment alone.** The in-process alternative is cheaper for a discrete spread in isolation; it was evaluated and set aside for longevity reasons (see the In-Process vs File-Bridge evaluation, 2026-06-03).

2. **Validate the pipes with a trivial basket first.** The first live basket is the *simplest possible* 2-leg pair on min lots -- even a near-zero-edge pair -- to prove dispatch / orphan handling / restart-reconcile / circuit breaker. Swap in the real research-approved cointegration strategy only after the infra is trusted. This decouples **infra risk** from **edge risk** and directly serves "validate infra, not returns."

---

## V0 -- minimal core (file-bridge shape)

Two processes + one append-only bridge file. The basket mechanic stays on the Trade_Scan side (reusing the validated `basket_runner`/`basket_pipeline`); TS_Execution gains only a thin **shim** + the atomic multi-leg dispatch primitive.

```
Trade_Scan side -- live basket runner (reuses the validated mechanic)
  each closed 5m bar:
    pull both legs' bars -> both-legs-fresh gate -> run mechanic
    emit DESIRED TARGET STATE: {FLAT | IN(direction, legs, per-leg lots)}
    append to TS_SIGNAL_STATE/h2_live/target.jsonl   (atomic write, single writer)

TS_Execution side -- thin shim (only new executor code)
  poll target.jsonl every N s:
    read latest target + read live broker positions
    reconcile actual -> target:
      need OPEN  -> dispatch_group(legs)   [atomic multi-leg market]
      need CLOSE -> close_group(legs)
      matches    -> no-op
    write result -> TS_SIGNAL_STATE/h2_live/executions.jsonl   (atomic)
```

**Why target-state, not events:** the runner publishes *what the position should be*, not ENTER/EXIT edges. The shim's only job is "make the broker match the latest target." This makes restart trivially safe (read latest target + broker truth, converge) and removes the missed-event / split-brain failure mode an event stream would introduce.

**The one new execution primitive:** `dispatch_group` -- atomic multi-leg market with the failure protocol (entry partial -> flatten + abort; exit partial -> retry once -> HALT + alert). Everything else reuses the existing shell: `broker.py`, `risk.py`, watchdog, heartbeat, Phase 0, staleness guard.

V0 deliberately uses: target-state reconciliation, fixed per-leg lots (beta ratio), market orders, 2 legs, one basket, discrete FLAT/IN, manual fidelity review.

---

## Extension seams (so increments bolt on without redesign)

| Seam | Where | V0 behavior | Future increment |
|---|---|---|---|
| Mechanic | Trade_Scan runner | z-reversion -> FLAT/IN | recycle, CointTrigger, H3 -- same runner |
| Target/action vocabulary | bridge schema | `{FLAT, IN}` | `+ per-leg {RECYCLE, HARVEST, FREEZE}` deltas |
| Sizing | runner emits lots | fixed per-leg, beta ratio | dynamic / risk-based |
| Dispatch | TS_Execution shim | 2-leg market reconcile | N-leg, limit orders, add-to-leg |
| Verification | reads `executions.jsonl` | manual review | automated fidelity reader (bridge makes this trivial) |

V0 is a strict subset of the eventual capability; each increment maps to one seam -- and all basket *intelligence* stays in the Trade_Scan runner, so TS_Execution's only governed dependency remains `engine_abi`.

**Bridge-specific invariants (in addition to the architecture-neutral Non-negotiables below):**
- **Single writer per file** (runner -> `target.jsonl`; shim -> `executions.jsonl`); atomic tmp+rename.
- **Shim is the sole reconciler against broker truth** -- target is desired, broker is actual; never replay past actions.
- **Two-process supervision** -- the watchdog must cover BOTH runner and shim. **Runner-death policy: RESOLVED by Review #4** -- hold last target + alert; no shim override authority; the always-on equity circuit breaker bounds the downside while blind.

---

## Non-negotiables for V0 (hard invariants)

1. **All-legs-or-no-legs.** Entry partial -> flatten + abort (harmless, you're flat). Exit partial -> retry once -> HALT + alert (a stuck-open leg is naked risk; never silent-continue). Fixed timeout + fixed retry; no discretion.
2. **Reconcile-on-restart from broker truth.** After any crash/restart, recover "is this basket open, with which legs?" from MT5 positions, NOT local files. This is the backbone -- get it wrong and you get double-entries / missed exits.
3. **Hedge ratio preserved by fixed lots.** A cointegration spread is `A - beta*B`; equal lots on two instruments with different pip/contract values is a *different* spread than was backtested. "Fixed lots" = fixed per-leg lots chosen to match the research beta, rounded to lot step.
4. **Both-legs gate.** No action unless both symbols are open, tradeable, and have fresh, gap-aligned bars; else deterministic no-op.
5. **Account circuit breaker stays armed** (`risk.py`). Optional: a per-basket hard stop for the first deployment.
6. **Single instance, no double-entry** (existing launcher/watchdog singleton guards).

---

## Multi-leg dispatch & orphan handling (Review #2, 2026-06-03)

MT5 has **no atomic multi-leg order**; "atomic basket" = sequence -> compensate -> reconcile-to-broker-truth. Design-level conclusions:

1. **Entry/exit asymmetry.** Entry partial -> close filled leg, abort OPEN (back to flat; harmless). Exit partial -> naked-leg live risk -> retry; if unresolved -> HALT + alert + operator. Never silent-continue on exit.
2. **Timeout != failure.** A timed-out order may still fill later; never infer fill state from a missing response -- reconcile against broker positions first.
3. **Broker-truth reconciliation after any uncertainty** (timeout / disconnect / reject / partial). The shim never trusts an order response in isolation. Orphan handling = the target-reconcile loop at order granularity.
4. **Order tagging** (magic/comment = basket + leg [+ epoch]) so leg state is answerable from broker positions; retries never blind-double-send.
5. **Bounded retry + HALT.** After K reconcile+retry cycles -> `ORPHAN_UNRESOLVED` -> HALT + alert + operator-clear.
6. **P2 (demo) must intentionally induce failures** -- reject leg on entry (assert rollback-to-flat), reject leg on exit (assert retry-then-HALT), kill MT5 mid-sequence (assert reconcile-on-reconnect), force timeout-then-late-fill (assert no double-position). Live only after every cell is deterministic.

Open decisions: deviation/slippage cap (lean loose, measure); entry leg ordering (harder-to-fill leg first); per-order timeout + retry count; `ORPHAN_UNRESOLVED` operator-clear procedure.

Reuse: extend TS_Execution `reconcile.py` (slot<->MT5 sync) to the 2-leg group; do not reinvent.

---

## Restart-reconcile protocol (Review #3, 2026-06-03)

**Restart is not a special mode -- it is the first reconcile cycle with empty memory.** For V0 the shim holds **no durable local state**: every decision derives from (latest target) + (broker positions, tag-filtered) each cycle. No separate recovery / reconnect / repair modes.

One loop, every cycle (including first-after-restart):
`read target -> read broker (by tag) -> classify -> converge` (via the Review-#2 dispatch state machine).

**Design invariant:** the broker must be either **coherent-at-target** or **flat**; any **incoherent** intermediate (one-leg, partial, mismatched) is **temporary and must be resolved by reconcile.**
- **V0 policy for incoherent states: flatten -> re-converge** (do not "complete" a half-open basket -- its entry price is now stale).
- **Scope: this flatten rule is a V0 POLICY, not universal doctrine.** Future recycle mechanics may have incoherent states that resolve to something other than flat; revisit the resolution rule per-mechanic when recycle becomes active.

**Statelessness linchpin:** order tags live on the broker (magic/comment = basket+leg[+epoch]) -- positions are self-identifying and survive restart in the broker, not a file. (The Review-#1 epoch extension also rides in the tag, so the shim stays stateless even when recycle arrives.)

**Convergence finding:** Reviews #1 (target-state), #2 (orphan handling), #3 (restart) all reduce to **broker-truth + one reconcile loop**. Orphan handling is not a separate subsystem -- entry/exit partial, timeout, disconnect, and restart are all just *incoherent states* the loop resolves. Three independent reviews arriving at one mechanism = evidence of the right abstraction.

**Boundary (hands off to Review #4):** reconcile is correct only if the *target is valid*. A stale target from a dead runner is the unresolved case -> Review #4 (runner-death). Residual: an order in-flight at the broker during the restart instant resolves next cycle (the tag check prevents double-send).

---

## Runner-death policy (Review #4, 2026-06-03)

**The question (sharpened):** not "hold or flatten?" but **"under what conditions does the shim gain authority to override the last target?"** -- the shim is a pure reconciler with no strategy authority.

**Detection:** trigger on **runner heartbeat staleness** (a liveness signal separate from the target), NOT target-freshness -- a HOLD and a dead runner look identical if you only watch the target. **Market-hours-aware** (legitimate closure != death; reuse the both-legs market-open check). The **watchdog** is the detector + first responder.

**Two regimes:**
- *Transient death (crash):* watchdog restarts the runner -> fresh target in seconds -> reconcile resumes. The shim **holds** during the gap. No decision needed (the common case).
- *Persistent death (won't restart / storm-guarded):* prolonged blind period -- the only place a policy bites.

**Authority model (the resolution):** separate two authorities --
- *Strategy authority* ("what to hold") lives only in the runner, via targets. The shim never has it.
- *Capital-preservation authority* ("flatten/halt to stop losses") lives in `risk.py`, is **always-on**, triggered by **equity, not runner liveness**.

**Runner-death pauses strategy authority; it does not transfer it to the shim.** During a blind hold, the only autonomous position action is the equity circuit breaker -- which already covers the only real danger of being blind (a runaway loss).

> **V0 policy: HOLD last target + escalate alert. Shim gains NO override authority. The pre-existing equity circuit breaker bounds the downside.** Time-based **grace->flatten is rejected for V0** -- redundant with the circuit breaker, and it would flatten a fine position on a false-positive (briefly-slow runner), with the flatten itself able to orphan during the disconnect that caused the death.

**Lever if a blind hold feels too risky:** tighten the **capital** guard -- add a **per-basket hard stop** -- NOT liveness-triggered flatten. Keeps every autonomous position action equity-triggered, and composes with Review #3 (a per-basket stop hit while blind -> the reconcile loop takes it to flat normally). **Keep the per-basket stop as an explicit FUTURE TUNING KNOB:** the account breaker (portfolio survival) and a spread-specific stop (this basket's risk) solve **different problems** -- do not build for V0, do not close the door.

**Out of scope (named, not solved):** *runner alive but emitting wrong targets* (fresh heartbeat, bad intent) is a correctness failure, not a liveness failure -- caught by the parity/fidelity checks + circuit breaker, not by death detection.

**Open knobs (tuning, not new authority):** heartbeat staleness threshold; whether/where to set a per-basket stop; watchdog restart-storm-guard -> operator-escalation timing.

---

## Trivial-basket-first (Review #5, 2026-06-03)

**Verdict: trivial-first holds** (decision 2 confirmed), with a sharpened definition + a complementarity note.

**Why it has operational value:** the first live multi-leg execution is the peak moment for an *infrastructure* bug. After research approval the **edge is the proven part; the live infra is the unproven part** -- expose the infra with stakes you're indifferent to. It also removes a confound: go straight to the real basket and an early misbehavior is ambiguous (infra bug vs bad luck on the edge). Trivial-first retires one risk before introducing the other.

**Sharpened definition:** "trivial" = **economically boring but executionally representative** -- same code paths (2-leg enter/exit, forced restart, the failure cells). A *truly inert* basket that never trades proves nothing.

**Complementary to P2, not redundant:**
- *P2 (demo)* retires **failure-logic** risk (induced reject/timeout/disconnect; no money).
- *Trivial-at-L0 (real account)* retires **live-account-path** risk (real fills, slippage, swap, login/symbol-subscription/`MT5_EXE_PATH`, circuit breaker wired to **live** equity) with throwaway stakes -- things a demo account does not faithfully reproduce.

**Make it a bounded checklist, not an open-ended run:** a few clean enter/exit cycles, one forced restart while in-position (assert reconcile converges), observe >=1 real fill's slippage, confirm the circuit breaker trips on a contrived threshold -> then swap in the real approved strategy.

**Cost:** a little time + a little spread/slippage = cheap insurance against the asymmetry (an infra bug found *with* the real strategy = real-capital incident + diagnostic ambiguity). The infra is brand-new (never run live multi-leg) -- there is no scenario where skipping is lower-risk.

---

## Deferred (explicitly OUT of V0)

Dynamic sizing; recycle / add / harvest mechanics; limit orders / slippage optimization; multi-basket portfolio; an automated fidelity *daemon*; broker-data cross-check; anything validator-shaped. Each maps to a seam above and is added only after V0 is trusted. (The file-bridge runner itself is **in** V0 -- it is the chosen execution path, not deferred.)

---

## Promotion-to-live workflow

1. **Research** -> cointegration basket reaches PIPELINE_COMPLETE; quality + expectancy gate runs on the **basket's combined PnL** (note: NOT the existing per-symbol all-or-nothing logic -- a spread is one combined equity; the gate needs that shape).
2. **`/promote` (basket-aware)** -> vault snapshot (legs + beta/lot ratio + params + engine + strategy hashes) -> `portfolio.yaml` basket entry (legs, per-leg direction, per-leg fixed lot).
3. **Parity gate** -> replay the promoted basket on its own backtest bars -> expect exact-match trades. Hard stop on mismatch. (This is the lean replacement for the retired validator: confirms deployed == promoted, like-with-like.)
4. **Phase 0** -> both legs load, ABI matches, hashes match the vault.

---

## Validation stages (binary, evidence-gated -- no compression)

| Stage | What | Capital |
|---|---|---|
| **P0** Offline parity | deployed reproduces promoted on backtest bars | none |
| **P1** Dry-dispatch | live signal loop on live bars; dispatch logs "would-send", does not send | none |
| **P2** Demo account | real multi-leg sends to a DEMO MT5 account; **deliberately induce a leg failure** to prove flatten/halt + restart-reconcile | none |
| **L0** Live min lots | real account, fixed lots in beta ratio, ONE basket, tight circuit breaker, 24-48h manual fidelity watch | minimal |
| **L1** Steady | run under watchdog + circuit breaker; daily fidelity check | minimal |

Each stage must be clean before the next.

---

## Biggest operational risks

1. **Stuck-open leg on exit failure** -> unbounded naked risk. (Halt + alert; never silent-continue.)
2. **State desync after restart** -> double-entry / missed exit. (Reconcile from MT5 truth.)
3. **Hedge-ratio vs fixed-lot mismatch** -> live != backtest. (Lots in research beta ratio.)
4. **Thin edge vs slippage** on market orders -> edge eaten. (Min lots; measure realized vs expected.)
5. **Stale/gap data on one leg** -> corrupt spread -> wrong signal. (Both-legs-fresh gate.)
6. **Deploying unproven edge** -> research verdict is currently open. (Hard gate: research approves first.)
7. **Runner death = strategy goes blind** (two-process bridge) -> positions stay open with no new exit signals. **Resolved (Review #4):** hold last target + alert; downside bounded by the always-on equity circuit breaker; no shim override authority.

---

## Prerequisites / open decisions

- **Research must APPROVE** a cointegration basket through the canonical pipeline -- not yet done; this is the #1 gate.
- The coint backtest behind any promotion must use the **screener's per-pair window** (not a fixed 2-year span) -- per `feedback_test_window_must_match_signal_class`; window/signal-class mismatch is a known cointegration failure mode.
- Define the **basket quality-gate shape** (combined-PnL, not per-symbol all-or-nothing).
- Choose the **first pair** and its **beta -> per-leg lot** mapping.
- Ops: fix `MT5_EXE_PATH` (known wrong default), ensure both symbols subscribed, account funded, DATA_INGRESS fresh.
- **Target-state contract (reviewed 2026-06-03):** pure target-state is sufficient for the discrete cointegration first deployment. It **may not cover all long-term mechanics** -- `soft_reset_basket` (live in H2_recycle@4/@5) and the planned `realize_winner` do full-realize-and-reopen / basis-reset that a net-vector target cannot express. **Candidate extension: a per-leg `epoch` tag.** Not needed for coint; **do not build now; revisit when recycle becomes active.**

**Runner-death policy -- RESOLVED by Review #4 (2026-06-03):** V0 = hold last target + escalate alert; the shim gains no override authority; the always-on equity circuit breaker bounds the downside while blind; time-based grace->flatten rejected for V0. Full authority model + the per-basket-stop future knob are in the Runner-death section above.

---

## Don't-do list

- Don't rebuild the validator (the post-deploy fidelity check is a thin log reader / manual review, not a replay engine).
- Don't carry over the old H2 live-execution plan's *validator* assumptions. The file-bridge *pattern* is retained as current preference (decision 1), but its details must be re-derived without the validator and against the actual first-strategy mechanic.
- Don't put the best unproven strategy live first -- prove the machine with a boring basket, then trust it with the edge.
