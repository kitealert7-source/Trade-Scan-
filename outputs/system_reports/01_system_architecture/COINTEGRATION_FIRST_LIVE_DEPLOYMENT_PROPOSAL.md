# Cointegration -- First Live Deployment (Design Proposal)

**Status:** DRAFT / PROPOSAL -- brainstorming phase, no code. NOT locked governance.
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
- **Two-process supervision** -- the watchdog must cover BOTH runner and shim. Runner-death policy is explicit (V0: shim holds the last target + alerts on runner staleness; it does NOT self-flatten).

---

## Non-negotiables for V0 (hard invariants)

1. **All-legs-or-no-legs.** Entry partial -> flatten + abort (harmless, you're flat). Exit partial -> retry once -> HALT + alert (a stuck-open leg is naked risk; never silent-continue). Fixed timeout + fixed retry; no discretion.
2. **Reconcile-on-restart from broker truth.** After any crash/restart, recover "is this basket open, with which legs?" from MT5 positions, NOT local files. This is the backbone -- get it wrong and you get double-entries / missed exits.
3. **Hedge ratio preserved by fixed lots.** A cointegration spread is `A - beta*B`; equal lots on two instruments with different pip/contract values is a *different* spread than was backtested. "Fixed lots" = fixed per-leg lots chosen to match the research beta, rounded to lot step.
4. **Both-legs gate.** No action unless both symbols are open, tradeable, and have fresh, gap-aligned bars; else deterministic no-op.
5. **Account circuit breaker stays armed** (`risk.py`). Optional: a per-basket hard stop for the first deployment.
6. **Single instance, no double-entry** (existing launcher/watchdog singleton guards).

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
7. **Runner death = strategy goes blind** (two-process bridge) -> positions stay open with no new exit signals. (Watchdog covers both processes; alert on runner staleness; V0 policy = hold last target + alert, do not self-flatten.)

---

## Prerequisites / open decisions

- **Research must APPROVE** a cointegration basket through the canonical pipeline -- not yet done; this is the #1 gate.
- The coint backtest behind any promotion must use the **screener's per-pair window** (not a fixed 2-year span) -- per `feedback_test_window_must_match_signal_class`; window/signal-class mismatch is a known cointegration failure mode.
- Define the **basket quality-gate shape** (combined-PnL, not per-symbol all-or-nothing).
- Choose the **first pair** and its **beta -> per-leg lot** mapping.
- Ops: fix `MT5_EXE_PATH` (known wrong default), ensure both symbols subscribed, account funded, DATA_INGRESS fresh.

---

## Don't-do list

- Don't rebuild the validator (the post-deploy fidelity check is a thin log reader / manual review, not a replay engine).
- Don't carry over the old H2 live-execution plan's *validator* assumptions. The file-bridge *pattern* is retained as current preference (decision 1), but its details must be re-derived without the validator and against the actual first-strategy mechanic.
- Don't put the best unproven strategy live first -- prove the machine with a boring basket, then trust it with the edge.
