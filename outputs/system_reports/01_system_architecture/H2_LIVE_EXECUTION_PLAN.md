# H2 Live Execution Plan

**Status:** PROPOSAL (depends on `H2_PLAN_REVISION_PROPOSAL_2026-05-15.md` being approved Monday). If revision rejected, this plan is discarded; the H2-live path falls back to the original v11 §Phase Map 7b → 8 → 8.5 sequence.

**Goal:** Take H2 EUR+JPY recycle basket from "research-validated + Phase 7a CODE-COMPLETE" to "live $1k stake trading on OctaFx via TS_Execution".

**Scope is strictly H2.** Per-symbol strategies (PINBAR, KALFLIP, etc.) are outside this plan; they continue under the original 7b/8/8.5 trust-progression.

**Calendar estimate:** ~1 week from approval to live, dominated by event-gated dry-run window (Step 3 — runs until coverage criteria C1–C4 are met; typically 1–3 days of live ticks, longer if recycle conditions don't naturally occur). ~3 sessions of code work.

---

## 0. Prerequisites (verify before starting Step 1)

- [ ] Phase 7a Stage 5 PASSED Monday (validator survived weekend with no unexplained stale-heartbeat events vs DISRUPTION_LOG)
- [ ] Plan revision approved (this plan depends on it)
- [ ] Operator-side cleanup pass done (worktrees, orphan state dirs — per cleanup backlog)
- [ ] H2 P00 vault present at `DRY_RUN_VAULT/baskets/90_PORT_H2_5M_RECYCLE_S01_V1_P00/H2/` ✅ confirmed (Phase 5b.2)
- [ ] `governance/recycle_rules/registry.yaml` has `H2_recycle@1` registered ✅ confirmed
- [ ] `tools/recycle_rules/h2_recycle.py` is the validated mechanic (Variant G + harvest + compression) ✅ confirmed (commit `4f5e2fc`)
- [ ] OctaFx MT5 terminal accessible + the EURUSD + USDJPY symbols subscribed
- [ ] USD_SYNTH `compression_5d` daily file is being kept fresh by `DATA_INGRESS` (used by the recycle rule's regime gate)

---

## 1. Step 1 — basket_pipeline live MT5 adapter (~1 session)

**Why:** `basket_pipeline` already runs the H2 mechanic correctly (10/10 windows in research). Only missing piece is a data feeder that pulls live 5m bars from MT5 each bar-close instead of frozen RESEARCH csv.

### Deliverables

- New file `tools/basket_live_data_loader.py`:
  - Mirrors the surface of `tools/basket_data_loader.py` (returns `{symbol: DataFrame}` with the same OHLC + compression_5d columns)
  - Pulls bars from MT5 via the existing `mt5_feed.py` adapter (or equivalent in `TS_Execution/src/`)
  - Forward-fills the daily compression_5d series onto the 5m index, lookahead-safe `shift(1)` (matching the proven research-mode lookahead handling — Phase 5d.1 fix)
- `tools/basket_pipeline.py` extension: accept `data_loader` argument so callers can swap research-mode loader vs live-mode loader. Default unchanged → research mode.
- Live-mode invocation entry point `tools/run_basket_live.py`:
  - **Market-closed gate (closes audit point 13 — operator critique 2026-05-15):** at the top of each cycle, check `is_market_open(symbol)` for both EURUSD and USDJPY via `mt5.symbol_info(symbol).trade_mode`. If either is closed, the cycle is a strict no-op:
    ```
    no new actions emitted
    no recycle evaluation performed
    state persists unchanged in basket_state.json
    log: {"market_closed": true, "ts": ..., "next_check_at": ...}
    sleep until next bar boundary, recheck
    ```
    No operator discretion, no override flag in the runner. The market-closed branch is purely deterministic.
  - When market reopens (next cycle finds `is_market_open == True` for both legs), evaluation resumes from the same in-memory aggregator state. The first post-reopen bar is treated as the next normal bar — no special "first bar of session" handling.
  - Pulls latest closed 5m bar (only when market is open)
  - Feeds basket_pipeline with rolling window of last N bars (enough for indicators + the recycle rule's bookkeeping)
  - basket_pipeline emits per-bar `BasketAction` records: `{action: HOLD|RECYCLE|HARVEST|FREEZE|OPEN, leg_changes: [...], reason, ts, expected_pnl_change}`
  - Action records appended to `TS_SIGNAL_STATE/h2_live/actions.jsonl` for TS_Execution shim consumption (atomic-write protocol — same as decision_emitter)

### Code touch areas
- NEW: `tools/basket_live_data_loader.py` (~150 lines)
- NEW: `tools/run_basket_live.py` (~100 lines)
- EDIT: `tools/basket_pipeline.py` add data_loader injection point (~20 lines)
- NEW: `TS_SIGNAL_STATE/h2_live/` directory schema (state-root extension)

### Pass criteria for Step 1
- `python tools/run_basket_live.py --once` (run once against the latest 5m bar) emits a `BasketAction` to `actions.jsonl` with deterministic content given the bar
- Action shape matches the schema TS_Execution shim consumes (Step 2 contract)
- Lookahead-safe: same compression_5d value as research run on overlapping data
- Tests: 5+ unit tests covering happy path, no-bar-yet, missing compression, gap-bar handling

### Rollback
- Revert the 4 files. No persistent state changes outside `TS_SIGNAL_STATE/h2_live/` (which can be deleted).
- basket_pipeline's research-mode default unchanged → existing tests still pass.

---

## 2. Step 2 — TS_Execution H2 shim (~1 session)

**Why:** TS_Execution today runs per-symbol strategies via its own dispatch loop. H2 needs multi-leg dispatch + recycle execution, but instead of building H2-specific logic into TS_Execution we bridge via the `actions.jsonl` file from Step 1.

### Deliverables

- New file `TS_Execution/src/h2_shim.py`:
  - Polls `TS_SIGNAL_STATE/h2_live/actions.jsonl` every N seconds
  - For each new action record, translates to MT5 order calls via existing `mt5_api.py`:
    - `OPEN`: 2 sequential market orders (EURUSD long 0.02, USDJPY long 0.01) under the orphan-leg protocol below
    - `RECYCLE`: close winner leg at market + place add-lot order on loser leg, sequenced under the orphan-leg protocol; update internal weighted-avg-entry tracker on full success
    - `HARVEST`: close all open legs at market, sequenced under orphan-leg protocol
    - `FREEZE`: no order; just log
    - `HOLD`: no-op
  - Writes execution results back to `TS_SIGNAL_STATE/h2_live/executions.jsonl` (atomic-write)
- TS_Execution `portfolio.yaml` entry for H2 with `vault_id: 90_PORT_H2_5M_RECYCLE_S01_V1_P00`, `mode: shim`, `paper_trading: true` (initially)
- Idempotency: shim tracks a `last_processed_action_id` to avoid replaying actions on restart

### Orphan-leg policy (closes audit point 12 — operator critique 2026-05-15)

**Problem:** H2 assumes coupled exposure across both legs. Any single-leg execution
(leg 1 fills, leg 2 rejects/requotes/freezes/times out) breaks the strategy's PnL
math immediately and leaves the basket in a state the recycle rule was never
designed for.

**Policy: Option A — Immediate Rollback (deterministic, operator-chosen 2026-05-15).**

```
For each multi-leg action (OPEN, RECYCLE, HARVEST):

  1. Sequence the per-leg orders. Each order has a hard timeout
     (default 5s; configurable per action type).

  2. After leg N's order:
       Status SUCCESS                -> proceed to leg N+1
       Status REJECTED / REQUOTED    -> trigger rollback (see step 4)
       Status PARTIAL_FILL           -> treat as failed; trigger rollback
       Status TIMEOUT (>5s no fill)  -> trigger rollback
       Status MT5_DISCONNECT         -> trigger rollback

  3. After all N legs SUCCESS: action complete. Write SUCCESS row to
     executions.jsonl.

  4. ROLLBACK procedure (when any leg N+1 fails after legs 1..N succeeded):
       a. For each successful prior leg (in reverse order):
            place opposite-direction market close order at qty = filled qty
            with same 5s timeout
       b. If rollback close succeeds for all prior legs:
            Write ROLLED_BACK row to executions.jsonl with
            {failed_leg, fail_reason, rollback_legs[], rollback_status: CLEAN}
            Mark action_id as terminal-failed (do NOT retry)
            Continue polling for next action
       c. If any rollback close itself fails:
            Mark basket state ORPHAN_UNRESOLVED in
            TS_SIGNAL_STATE/h2_live/basket_state.json
            HALT shim (do not process any further actions until operator clears)
            Write ESCALATION row to executions.jsonl + emit a separate
            TS_SIGNAL_STATE/events/orphan_alert.jsonl entry
            Operator must manually reconcile MT5 positions, then clear the
            ORPHAN_UNRESOLVED flag to resume

  5. The basket_pipeline live runner (Step 1) detects ROLLED_BACK actions on
     its next cycle and treats the basket as if the action never happened —
     no state mutation, no strategy advancement. The next cycle's evaluation
     re-derives the action from current bar data.
```

**Why Option A vs Option B (freeze + operator):**
- Deterministic: shim handles the failure without human in the loop for the common
  case (transient broker issues)
- Self-healing: clean rollback + retry-on-next-cycle means transient MT5
  hiccups don't require operator intervention
- Auditable: every rollback writes a structured row
- Escalation only when truly unrecoverable (rollback itself fails)
- ORPHAN_UNRESOLVED is a HARD halt — the operator MUST act before any further
  trading; cannot be silently skipped

**Implementation budget:** ~80–100 additional LOC in `h2_shim.py` + a new
`basket_state.json` schema (small).

### Code touch areas
- NEW: `TS_Execution/src/h2_shim.py` (~330–350 lines, including ~80–100 LOC for orphan-leg policy)
- EDIT: `TS_Execution/src/main.py` to launch shim alongside per-symbol dispatch (~30 lines, behind a feature flag)
- EDIT: `TS_Execution/portfolio.yaml` add H2 entry
- NEW: `TS_SIGNAL_STATE/h2_live/` schema:
    - `actions.jsonl` (basket_pipeline → shim contract)
    - `executions.jsonl` (shim outcome including ROLLED_BACK / ESCALATION rows)
    - `basket_state.json` (leg-state snapshot — survives shim restart)
    - `last_processed_action_id` (idempotency token)
    - `events/orphan_alert.jsonl` (escalation surface — operator-monitored)

### Pass criteria for Step 2
- Unit tests: each action type translates to expected MT5 order shape (mocked `mt5_api`)
- Idempotency: same action processed twice → second run is a no-op
- Atomic write: same protocol Phase 7a Stage 3 pinned (cleanup-on-init, retry-on-WinError-5)
- `paper_trading=true` short-circuits at order placement: log the order, don't actually send

### Rollback
- Disable feature flag in `portfolio.yaml`. Shim dies; per-symbol dispatch unaffected.

---

## 3. Step 3 — Event-gated dry-run signal-correctness test (clock-agnostic)

**Why:** the only thing not yet proven is that live tick → action → order math is correct. Clock-bounded "24h pass" was the wrong shape — coverage of the binding events matters, not how long the test ran. The test is complete when every required event class has been observed and reconciled, regardless of whether that takes 8h or 48h or longer.

### Setup
- Run Step 1 + Step 2 with `paper_trading=true`
- Operator manually closes any leftover from prior testing in MT5
- Reconciliation log: `outputs/h2_live_test_reconciliation.csv` with columns:
  `event_id, ts, action_kind, computed_pnl, expected_pnl_formula, expected_pnl_value, abs_delta, ✅/❌, notes`

### Required coverage (binary checklist — test is NOT complete until all checked)

| | Coverage requirement | What proves it |
|---|---|---|
| C1 | **1 initial basket open** | Both legs OPEN at first 5m bar after launch — correct symbols, lots, directions; orphan-leg policy did NOT trigger |
| C2 | **2+ recycle events** | Two distinct RECYCLE actions execute end-to-end. Each must satisfy: trigger conditions all met, winner-close + loser-add sequence completes, weighted-avg-entry math correct |
| C3 | **1 restart while basket state exists** | Stop and re-start the live runner + shim while the basket is mid-cycle (i.e., positions open, prior recycle realized PnL on the books). On restart: state recovers correctly from `basket_state.json`; no duplicate actions; next bar resumes evaluation as if no restart happened |
| C4 | **PnL reconciliation of EVERY event** | For every action in actions.jsonl, the executed PnL (from MT5 trade history or paper-fill price) matches the strategy's expected PnL formula within tolerance (0.5% for paper; documented per-event) |

### Per-event correctness criteria (applied within C4)

- **OPEN**: 2 paper-orders logged with correct symbols (EURUSD, USDJPY), lots (0.02, 0.01), directions (LONG, LONG); orphan-leg sequencing observed (leg 2 fires only after leg 1 SUCCESS)
- **RECYCLE**:
  - Trigger conditions all true at action emission time:
    - `winner_leg_floating_pnl ≥ $10`
    - `loser_leg_floating_pnl < 0`
    - `compression_5d ≥ 10` (regime gate)
    - `dd_freeze` NOT active
    - `margin_freeze` NOT active
  - On commit:
    - Winner leg close: realized PnL matches `_leg_pnl_usd(winner, current_close)` formula
    - Loser leg add-lot: lot = 0.01; new total lot = old + 0.01; new weighted-avg entry = `(old_lot × old_avg + 0.01 × current_close) / new_lot`
    - State: `realized_total += winner_realized`; `harvested_total_usd` updated; recycle event appended to recycle_events
  - Both legs sequenced under orphan-leg protocol (Step 2 §"Orphan-leg policy")
- **HARVEST** (if observed — unlikely in any short test with $1k stake):
  - Equity reaches ≥ $2000
  - All open legs close at market under orphan-leg protocol
  - Subsequent bars: no further actions (basket terminal)
- **FREEZE** (if observed):
  - Logged with explicit cause (DD / margin / regime); no orders sent; no state mutation

### Coverage realism note

C2 (2+ recycle events) is the long-pole requirement. In RESEARCH-mode matrix data, recycle frequency varied 5–40 events per 2-year window depending on regime. In live 5m, expect roughly 0–5 per day depending on conditions. If after 48h C2 is still unmet:
- **Do NOT skip C2.** Do not flip to live without observing 2 recycles.
- Either: extend dry-run until 2 recycles occur naturally
- Or: synthesize a controlled trigger by temporarily lowering `trigger_usd` to $1 (artificial; clearly mark as a synthesized-trigger test event in the reconciliation log; restore $10 immediately after for the real test)

### What this test does NOT validate (acceptable)
- Real fill prices vs paper-trade prices (slippage). Observable in Step 4 with real money.
- Multi-week strategy performance variance. Already validated in research (10/10 windows).
- TS_Execution behavior under MT5 disconnects beyond what the orphan-leg policy covers. Same surface as any per-symbol live trade.

### Pass criteria for Step 3 (binary AND of all)
- C1, C2, C3, C4 all checked ✓
- Reconciliation log: every event row has ✅
- Zero spurious orders (orders only for emitted actions)
- Zero IO failures (atomic-write protocol holds across the run)
- Compression_5d value used in any RECYCLE matches the daily file's lookahead-safe `shift(1)` value (no live-bar lookahead)
- Restart in C3 left zero `.tmp` debris in `TS_SIGNAL_STATE/h2_live/`

### Rollback
- Stop the shim + the live runner. No financial impact (paper_trading=true throughout).
- Discard the actions.jsonl + executions.jsonl + basket_state.json as test debris.
- If a synthesized-trigger event was used for C2, restore `trigger_usd: 10.0` in the H2 directive before any further work.

---

## 4. Step 4 — Live deployment with $1k stake

**Trigger:** Step 3 passes (operator signs off after 24h).

### Procedure
- Edit `TS_Execution/portfolio.yaml` H2 entry: `paper_trading: false`, `starting_equity_usd: 1000`
- TS_Execution shim picks up flag flip on next polling cycle
- First action triggers real MT5 orders

### Operator monitoring
- Observe first complete harvest cycle:
  - Initial open fires correctly
  - First few recycle events (if any) execute correctly
  - Equity tracking matches independent calculation from MT5 trade history
- Heartbeat the operator's eyes daily for the first week
- After first harvest target hits: harvested_total_usd = ~$1k, basket auto-stops per spec

### Pass criteria for Step 4
- First harvest cycle completes successfully (TARGET hit OR equity stable through a typical recycle pattern)
- No stop-loss hit beyond the recycle rule's freeze thresholds (= mechanic working as designed)
- MT5 trade history matches actions.jsonl + executions.jsonl

### Rollback
- Set `paper_trading: true` in portfolio.yaml. Shim stops sending real orders.
- If positions are open, operator manually closes via MT5 UI.
- Investigate divergence; re-enter Step 3 if needed.

### Financial risk
- Worst case: $1k stake lost (recycle rule's intra-strategy freezes prevent further DD beyond the floor → effectively the $1k stake is the cap)
- Best case: $1k harvested then auto-stop (per H2 spec design)
- Asymmetric: capped downside, capped upside ($1k each direction). Self-limiting.

---

## 5. Step 5 (optional) — scale up if Step 4 validates

**NOT IN INITIAL SCOPE.** Drafted here so it's documented.

After 1 successful harvest cycle:
- Increase stake to $2k → harvest target $4k. Recycle rule scales.
- Add a second basket variant (G2, H2 with different params) parallel under the same shim
- Eventually: TS_Execution gets native H2 support (the original Phase 10 deliverable), shim retires

This step requires a separate review + approval. Do not jump straight to it.

---

## 6. What this plan deliberately defers

- **Phase 7b validator-shadow-read for H2.** The validator is not in H2's gating loop (recycle rule has its own freezes). The validator's role for H2 is observational/audit only. This is documented in the plan revision proposal §1n-NEW.
- **Phase 8.5 broker data cross-check.** Useful refinement but not gating live H2. Can be added Phase 11+ for the H2 audit surface.
- **Phase 9 matrix extension.** Independent research; can park indefinitely.
- **Multi-symbol TS_Execution upgrade.** Still required for *general* Phase 10. H2-live via the shim doesn't depend on it because the shim is H2-specific.

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| live MT5 5m bars differ from RESEARCH csv at boundary (gap, missing bar) | Medium | Could trigger an unexpected action | Step 1 includes gap-bar handling tests; Step 3 24h test will surface |
| `compression_5d` daily file goes stale (DATA_INGRESS broken) | Low | Recycle rule's regime gate would freeze; no false trades | Operator monitors DATA_INGRESS freshness (CLAUDE.md `## Data Freshness Detection`) |
| MT5 disconnect mid-action | Medium | Half-executed recycle (e.g., winner closed but loser-add failed) | **Closed by Step 2's orphan-leg policy** (disconnect = leg N+1 fails to fill within timeout = rollback). Idempotency on resume preserved by `last_processed_action_id` + ROLLED_BACK rows in executions.jsonl. |
| Slippage on real fills exceeds research-mode assumption | Medium | Slightly worse PnL than research baseline, but recycle rule's freezes still apply | Acceptable trade-off; observe in Step 4 |
| Operator misinterprets a freeze as a malfunction | Low | Manual intervention could disrupt the mechanic | Documentation + operator briefing before Step 4 |
| Real-world weekend / holiday behavior (no bars 22:00 Fri → 22:00 Sun) | High (every weekend) | basket_pipeline would mis-evaluate against stale ticks if runner kept polling | **Closed by Step 1's deterministic market-closed gate.** Live runner checks `mt5.symbol_info(symbol).trade_mode` at every cycle; if either leg's market is closed, the cycle is a strict no-op (no actions, no evaluation, state preserved). No operator discretion. Weekend = quietly sleeps; market reopens = quietly resumes from the persisted aggregator state. See §1 "Market-closed gate" for the policy text. |
| Single-leg execution (leg 1 fills, leg 2 rejects/requotes/freezes) | Medium (occasional broker hiccups; FX is liquid but not perfect) | H2 assumes coupled exposure — orphan leg breaks the strategy's PnL math immediately | **Closed by Step 2's orphan-leg policy (Option A — immediate rollback).** Shim sequences legs with hard timeout, on any failure rolls back successful prior legs at market. ORPHAN_UNRESOLVED escalation only when rollback close itself fails. See §2 "Orphan-leg policy" for the policy text. |

---

## 8. Open questions for Monday review

1. ~~Is the `paper_trading=true` 24h window sufficient observation? Or do you want 48–72h?~~ — **resolved 2026-05-15:** Step 3 rewritten as **event-gated dry-run** (clock-agnostic; coverage-driven). C1+C2+C3+C4 binary checklist replaces wall-clock window. Doc §3.
2. Do you want the shim's actions.jsonl + executions.jsonl committed to a Git repo (audit trail) or kept as state only?
3. Should we add a hard "kill-switch" that the operator can flip to pause H2 between recycle cycles? (Independent of the shim's poll loop, the orphan-policy ESCALATION halt, and the market-closed gate)
4. After Step 4's first harvest cycle, what's the policy on auto-restart vs operator-confirms-restart?
5. Synthesized-trigger fallback for C2 (Step 3 §"Coverage realism note") — acceptable or stricter "no synthesis"?

---

## 9. Audit items resolved in this revision (2026-05-15)

| # | Concern | Where it's addressed |
|---|---|---|
| 12 | Shim partial-fill / orphan-leg handling under-specified | §2 "Orphan-leg policy" — explicit Option A immediate-rollback procedure with ESCALATION fallback |
| 13 | Weekend / market-close handling too loose ("pause live runner") | §1 "Market-closed gate" — deterministic `mt5.symbol_info(symbol).trade_mode` check at every cycle; no operator discretion |
| — | Step 3 was clock-bounded ("24h pass") | §3 rewritten as event-gated; coverage matters not clock; explicit C1–C4 checklist + per-event PnL reconciliation |

---

*Drafted 2026-05-15 during Stage 5 weekend run. Read-only doc; no operational state touched. Companion: `H2_PLAN_REVISION_PROPOSAL_2026-05-15.md`.*
