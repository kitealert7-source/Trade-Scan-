# H2 Live Execution Plan

**Status:** PROPOSAL (depends on `H2_PLAN_REVISION_PROPOSAL_2026-05-15.md` being approved Monday). If revision rejected, this plan is discarded; the H2-live path falls back to the original v11 §Phase Map 7b → 8 → 8.5 sequence.

**Goal:** Take H2 EUR+JPY recycle basket from "research-validated + Phase 7a CODE-COMPLETE" to "live $1k stake trading on OctaFx via TS_Execution".

**Scope is strictly H2.** Per-symbol strategies (PINBAR, KALFLIP, etc.) are outside this plan; they continue under the original 7b/8/8.5 trust-progression.

**Calendar estimate:** ~1 week from approval to live. ~3 sessions of code work. 1 day of paper-trading observation.

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
  - Pulls latest closed 5m bar
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
    - `OPEN`: 2 simultaneous market orders (EURUSD long 0.02, USDJPY long 0.01)
    - `RECYCLE`: close winner leg at market, place add-lot order on loser leg, update internal weighted-avg-entry tracker
    - `HARVEST`: close all open legs at market
    - `FREEZE`: no order; just log
    - `HOLD`: no-op
  - Writes execution results back to `TS_SIGNAL_STATE/h2_live/executions.jsonl` (atomic-write)
- TS_Execution `portfolio.yaml` entry for H2 with `vault_id: 90_PORT_H2_5M_RECYCLE_S01_V1_P00`, `mode: shim`, `paper_trading: true` (initially)
- Idempotency: shim tracks a `last_processed_action_id` to avoid replaying actions on restart

### Code touch areas
- NEW: `TS_Execution/src/h2_shim.py` (~250 lines)
- EDIT: `TS_Execution/src/main.py` to launch shim alongside per-symbol dispatch (~30 lines, behind a feature flag)
- EDIT: `TS_Execution/portfolio.yaml` add H2 entry
- NEW: `TS_SIGNAL_STATE/h2_live/` schema (executions.jsonl, last_processed_action_id)

### Pass criteria for Step 2
- Unit tests: each action type translates to expected MT5 order shape (mocked `mt5_api`)
- Idempotency: same action processed twice → second run is a no-op
- Atomic write: same protocol Phase 7a Stage 3 pinned (cleanup-on-init, retry-on-WinError-5)
- `paper_trading=true` short-circuits at order placement: log the order, don't actually send

### Rollback
- Disable feature flag in `portfolio.yaml`. Shim dies; per-symbol dispatch unaffected.

---

## 3. Step 3 — 24h dry-run signal-correctness test (~1 calendar day)

**Why:** the only thing not yet proven is that live tick → action → order math is correct. 24h with `paper_trading=true` exercises this against real market data without financial risk.

### Setup
- Run Step 1 + Step 2 with `paper_trading=true`
- Operator manually closes any leftover from prior testing in MT5
- Open a tracking spreadsheet or just a markdown table with columns: ts, action, expected, actual, ✅/❌

### What to observe (24h)
- **Initial open** at session start: EUR-long 0.02 + USDJPY-long 0.01 fires at the first 5m bar after launch
  - Pass: 2 paper-orders logged with correct symbols, lots, directions
- **Continuous hold:** between recycle events, no spurious orders
  - Pass: actions.jsonl records HOLD actions only between RECYCLE / HARVEST events
- **Recycle triggers** (likely 0–3 in 24h based on matrix data):
  - Each trigger condition correctly evaluated:
    - winner_leg_floating_pnl ≥ $10 ✅
    - loser_leg_floating_pnl < 0 ✅
    - compression_5d ≥ 10 ✅ (regime gate)
    - dd_freeze NOT active ✅
    - margin_freeze NOT active ✅
  - On commit:
    - Winner leg: close order with realized pnl matching `_leg_pnl_usd(winner, current_close)` formula
    - Loser leg: add-lot order = 0.01; new leg lot = old + 0.01; weighted-avg new entry = `(old_lot × old_avg + 0.01 × current_close) / new_lot`
    - State: realized_total += winner_realized; harvested_total_usd updated; recycle event appended
- **Safety freezes** (less common in 24h; observe if conditions met):
  - DD freeze: floating_total < 0 AND |floating_total| ≥ 0.10 × equity → recycle blocked, no orders sent
  - Margin freeze: margin_used ≥ 0.15 × equity → recycle blocked
  - Regime freeze: compression_5d < 10 → recycle blocked
- **Harvest target** (unlikely in 24h with $1k stake unless huge move):
  - Equity ≥ $2000 → close-all paper orders + stop trading

### Pass criteria for Step 3
- Every event mathematically correct against expected formula (operator review of each one in actions.jsonl + executions.jsonl)
- Zero spurious orders
- Zero IO failures (atomic-write protocol holds)
- Compression_5d value used matches the daily file (no live-bar lookahead)

### Rollback
- Just stop the shim + the live runner. No financial impact. Discard the actions.jsonl + executions.jsonl as test debris.

### What this test does NOT validate (acceptable)
- Real fill prices vs paper-trade prices (slippage). Will be observable in Step 4 with real money.
- Multi-week strategy performance variance. Already validated in research.
- TS_Execution behavior under MT5 disconnects. Same as any per-symbol live trade.

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
| MT5 disconnect mid-action | Medium | Half-executed recycle (e.g., winner closed but loser-add failed) | TS_Execution mt5_api should already handle disconnect/retry; shim should be idempotent on resume |
| Slippage on real fills exceeds research-mode assumption | Medium | Slightly worse PnL than research baseline, but recycle rule's freezes still apply | Acceptable trade-off; observe in Step 4 |
| Operator misinterprets a freeze as a malfunction | Low | Manual intervention could disrupt the mechanic | Documentation + operator briefing before Step 4 |
| Real-world weekend / holiday behavior (no bars 22:00 Fri → 22:00 Sun) | High (every weekend) | basket_pipeline expects continuous bars; could log spurious gap | Step 1 includes weekend-aware bar-stream filter; or simply pause the live runner during weekend |

---

## 8. Open questions for Monday review

1. Is the `paper_trading=true` 24h window sufficient observation? Or do you want 48–72h?
2. Do you want the shim's actions.jsonl + executions.jsonl committed to a Git repo (audit trail) or kept as state only?
3. Should we add a hard "kill-switch" that the operator can flip to pause H2 between recycle cycles? (Independent of the shim's poll loop)
4. After Step 4's first harvest cycle, what's the policy on auto-restart vs operator-confirms-restart?

---

*Drafted 2026-05-15 during Stage 5 weekend run. Read-only doc; no operational state touched. Companion: `H2_PLAN_REVISION_PROPOSAL_2026-05-15.md`.*
