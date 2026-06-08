# CADJPYUSDCHF Live-Basket Producer — Slice-2 Implementation & Go-Live Observation

**Status:** Producer **IMPLEMENTED + committed**, running in **OBSERVATION mode** (publishing `FLAT`/`IN` targets + heartbeat to the canonical bridge `SIGNAL_DIR`, **no shim attached, no orders**). Shim `--live` is gated on the operator after the observation window. This completes **deferred item #1 — "Real `basket_pipeline` runner (emit target-state from the live mechanic)"** of `COINTEGRATION_FIRST_LIVE_DEPLOYMENT_PROPOSAL.md`.
**Date:** 2026-06-08
**Commits:** `821d4bb9` (Trade_Scan — producer) · `ea3df25` (TS_Execution — shim bidirectional open) · `9d39d53` (TS_Execution — main-daemon demo-account gate) · `d30631a` (TS_Execution — Windows-lock IO hardening).

**Why this document exists:** the producer was the only fully-new component in the live chain (research → bridge → shim). Building it surfaced two non-obvious facts that cost real investigation — the mechanic's **USD-reference data dependency** and the shim's **single-direction open bug**. This report captures the *exact wiring* and those lessons so a future session (more baskets, same strategy on other assets) does **not** re-investigate from scratch.

---

## 1. What this phase delivered

| Piece | Where | State |
|---|---|---|
| **Producer** (Option 2: own MT5 read) | `Trade_Scan/tools/live_basket/cadjpyusdchf_producer.py` | Built, validated offline + live, committed `821d4bb9`, **running in observation** |
| **Shim bidirectional-open fix** | `TS_Execution/src/basket_shim.py` (`_leg_orders_for_open`) | Committed `ea3df25` (+ `tests/test_basket_shim_bidirectional.py`) |
| Main-daemon demo gate (parallel safety) | `TS_Execution/src/account_gate.py` + `main.py` | Committed `9d39d53` |

The producer, per closed 15m bar: reads CADJPY+USDCHF (legs) + USDJPY+USDCAD (USD refs) OHLC from its **own** MetaTrader5 connection → runs the promoted mechanic via `run_basket_pipeline` → derives `FLAT`/`IN` Targets via `StreamingBasketRunner` → appends to `target.jsonl` (+ heartbeat) in the bridge dir. It writes **only** the bridge files; the TS_Execution shim places orders (demo-gated).

---

## 2. The chain (one line)

```
MT5 (4 symbols) → cadjpyusdchf_producer (own conn)
   → run_basket_pipeline (mechanic, fresh per bar) → per_bar_records
   → StreamingBasketRunner.on_closed_bar → target.jsonl + runner_heartbeat.json   [PRODUCER, Trade_Scan]
                         │  (single append-only bridge dir, stdlib contract)
                         ▼
   basket_shim.py --live → reconcile vs MT5 positions → dispatch_group/close_group → demo orders   [CONSUMER, TS_Execution]
```

Architectural boundary = the **bridge contract** (locked `bridge.py`); producer and consumer never import each other.

---

## 3. ⭐ FUTURE YOU — established integration facts (do NOT re-investigate)

All verified 2026-06-08 against live code. File:line are Trade_Scan unless prefixed `TSx:` (TS_Execution).

### 3.1 Producer wiring (the reusable recipe)
- **Load directive:** `parse_directive(Path)` from `tools.pipeline_utils` → `parsed["basket"]` = `{basket_id, legs:[{symbol,direction,lot}], recycle_rule:{name,version,params}}`.
- **Build leg_strategies (FRESH per replay call):** `PineZRevLegStrategy(symbol, position_direction=+1 if "long" else -1, armed_state=shared)` with **one shared `PineZRevArmedState()` per call** (the 2-bar entry protocol is shared across legs). Reusing it across prefix-replays pollutes state. `run_pipeline.py` `_build_pine_zrev_legs` / `_dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)` do this.
- **Run = the `replay_fn`:** `run_basket_pipeline(parsed, leg_data={sym: OHLC_df}, leg_strategies, run_id=, directive_id=).per_bar_records` (`tools/basket_pipeline.py:826`). It instantiates the **rule fresh internally** (`_instantiate_rule`); the caller passes directive+leg_data+leg_strategies only. **PURITY:** pass **copies** of the prefix frames (the run mutates `leg.df` in place).
- **Target derivation (reused, unchanged):** `StreamingBasketRunner(bridge_dir, basket_id, replay_fn, n_legs=2).on_closed_bar(dfA, dfB)` (`tools/live_basket/driver.py:97`) reads `per_bar_records[-1]`: `active_legs` (0=FLAT or n_legs=IN), `leg_{k}_symbol/side/lot`, `timestamp`; append-on-change; writes heartbeat every cycle; restores seq from the bridge on restart.
- **Warmup:** `required_warmup_bars = 2 * n_window` for `entry_mode=absolute` (n_window=30 → 60 bars). `<60` common bars → `RuntimeError` (fatal). Producer fetches `FETCH_N=500` and skips-emit when records empty.

### 3.2 ⚠️ Leg DataFrame contract — OHLC is **NOT** enough
The mechanic computes the z-signal from `close` (OHLC), **but** its per-bar **USD P&L + margin** (`_leg_pnl_usd_universal` / `_leg_margin_usd_universal` → `_usd_value_of_ccy`, `h2_recycle_v3.py`) need **USD-anchored reference closes** as `usd_ref_<PAIR>_close` columns (normally joined by `basket_data_loader.py:547` via `reindex(method="ffill")`). Missing them → `KeyError: 'USD...'`. `coint_regime` is **only** needed if `coint_break_exit=True` (deferred; this directive = False).

### 3.3 ⭐ The general rule for which USD-ref symbols a basket needs
For each leg, take **both** its base and quote currency. Map each non-USD currency via `_USD_REF` (`h2_recycle_v3.py:51`): `EUR→EURUSD, GBP→GBPUSD, AUD→AUDUSD, NZD→NZDUSD, JPY→USDJPY, CHF→USDCHF, CAD→USDCAD` (USD→none). **Drop** any pair that a leg *is* (USD-anchored legs self-reference, `_build_ref_closes`). The remainder = the external symbols to fetch + join as `usd_ref_<PAIR>_close`.
- **Worked example (this basket):** CADJPY → {CAD,JPY}, USDCHF → {USD,CHF}. CHF→USDCHF is the USDCHF leg (self-ref); USD→none. Remainder: **JPY→USDJPY (P&L), CAD→USDCAD (margin)**. ⇒ `USD_REF_SYMBOLS = ("USDJPY","USDCAD")`.
- (This was discovered the hard way — two sequential `KeyError`s in offline replay. The rule above lets the next basket compute it up front.)

### 3.4 MT5 reader + bridge path
- `copy_rates_from_pos(symbol, TIMEFRAME_M15, 0, N)` → ascending OHLC; **drop the forming bar** (newest) after sorting; `tick_volume`→`volume`; tz-naive `pd.to_datetime(time, unit="s")`. Align all symbol frames to a **common last closed bar** (a bar can form mid-fetch). Demo terminal `213872531 / OctaFX-Demo`.
- **Bridge dir (must byte-match both sides):** `<Documents>/TradeScan_State/TS_SIGNAL_STATE/h2_live/<BASKET_ID>/` — producer derives it from `__file__`; shim derives from `path_config.TRADESCAN_STATE` (`TSx:basket_shim.py`). Files: `target.jsonl`, `runner_heartbeat.json`, `executions.jsonl`.
- **Heartbeat freshness:** shim skips opens if `runner_heartbeat.beat_at` > **300s** stale. Producer polls every **60s** and refreshes the heartbeat every cycle (even on NOOP) — keep poll < 300s.

### 3.5 Shim consumer facts
- Reconcile identity = `(symbol, side, lot, epoch)` (`bridge/reconcile.py`) — direction-aware. `_leg_orders_for_open` keys **leg-index by SYMBOL** (`_SYMBOL_TO_IDX`; CADJPY=0, USDCHF=1) and takes broker buy/sell from the **target leg's side** → opens both spread directions. `_leg_orders_for_close` closes by magic; `close_all` derives the close side from the live `pos.type`. Hard demo gate `assert_demo_allowed` (account+server, not just trade_mode=DEMO).

---

## 4. Two lessons worth remembering

1. **OHLC ≠ enough for a cointegration basket** — the USD-ref data dependency (§3.2/3.3) is invisible until the mechanic computes P&L. Always derive the USD-ref set up front for a new basket/asset.
2. **`always_in_market: true` ⇒ the spread trades BOTH directions.** Offline replay showed **21/47 IN targets were short-spread** (CADJPY short / USDCHF long). The V0 shim's open was keyed by `(symbol, direction)` and rejected the short-spread → `ValueError` on ~45% of opens. Fixed in `ea3df25` (key by symbol). **Any bidirectional basket must have a symbol-keyed shim open.**

---

## 5. Validation evidence (no orders at any point)
- **Offline** (`--replay-csv`, RESEARCH CSVs, OHLC-only + USD refs): mechanic runs, clean `FLAT↔IN` sequence, per_bar_record contract satisfied.
- **Live read-only probe:** 4 symbols fetched (499 bars, aligned), mechanic → 454 records, current desired = `FLAT`.
- **Observation run** (canonical `SIGNAL_DIR`): `target.jsonl` = one `FLAT` line (append-on-change holds), `runner_heartbeat.beat_at` advancing each cycle. No shim, no orders.
- **Tests/gates:** `tests/test_basket_shim_bidirectional.py` (9: both-direction open, magic-by-symbol, unknown reject, lot-from-target, classify MATCH/NEED_OPEN/INCOHERENT/NEED_CLOSE); TS_Execution merge gate green; Trade_Scan pre-commit gate green (gate suite 70).
- **Adversarial reviews:** producer (4 lenses) + shim change (2 lenses) — PASS.

---

## 6. ⭐ What's left / how to extend (FUTURE YOU)

### 6.1 Adding the SAME strategy on DIFFERENT assets (e.g. another cointegrated pair)
Mostly mechanical given §3:
1. New promoted directive + descriptor for the new pair (research side).
2. New producer config: `BASKET_ID`, `_LEGS` (the two symbols + directions), `DIRECTIVE_ID/PATH`, and **`USD_REF_SYMBOLS` computed via the §3.3 rule** for the new currencies (do this first — it's the non-obvious bit).
3. Shim config (`TSx:basket_shim.py` `_LEGS`, `BASKET_ID`, `SIGNAL_DIR`) for the new basket. The open is now symbol-keyed, so both directions already work.
4. Re-run `--replay-csv` offline validation for the new pair before any live run (catches the next pair's USD-ref needs + warmup).
The current files are **hardcoded single-basket**; the clean step is to parameterize basket config (id/legs/usd_refs/directive/signal_dir) instead of copy-paste.

### 6.2 Adding MORE baskets (portfolio)
The blocker is **data-feed scaling, not logic**: each Option-2 producer opens its **own** MT5 connection. N baskets ⇒ N connections to one terminal ⇒ the contention cliff. This is the **trigger to migrate to Option 3** (TS_Execution publishes synchronized bars once; producers consume). Reversibility was verified: only the producer's **bar-source layer** changes (everything from `replay_fn`/`on_closed_bar` downstream — bridge, shim, schemas, promotion, vault — is untouched). So: build Option 2 per-basket until basket #2 forces centralized bars; the bridge contract is unchanged across the move.

### 6.3 Deferred hardening (intentionally out of V0 scope)
- **Track B2 — regime-break exit:** enable `coint_break_exit=True` + supply a fresh `coint_regime` column (daily, from `cointegration.db`, ffill). Producer must then join it (like the USD refs).
- **Track B3 — regime-freshness gate:** assert `coint_regime` `as_of` is recent before a regime-driven FLAT drives a live close.
- **Producer robustness:** restart persistence beyond bridge state, scheduler/supervision (Windows Task), reconnect/backoff/exit-on-N-errors, weekend-flatten policy (currently no proactive Fri-close flatten). Incremental windowing to replace the O(N²) prefix-replay (only matters at scale / long sessions).
- **Observability report:** join `executions.jsonl` (decision layer) + MT5 history (broker layer) into one chain — see the demo-observability plan.

### 6.4 Go-live sequence (the gated path)
1. Confirm terminal on demo `213872531`. 2. Run producer only → confirm `target.jsonl`+heartbeat update, current=FLAT (**done — observation mode now**). 3. Observe; wait for the first `IN` target (validates the bidirectional shim). 4. **Then** `python src/basket_shim.py --live` (separate process, demo-gated) → executes the 2-leg group. 5. Watch `executions.jsonl` + MT5 positions + empty `halts/`. **First real demo lifecycle = the next milestone.**

---

*Cross-refs: `COINTEGRATION_FIRST_LIVE_DEPLOYMENT_PROPOSAL.md` (design + deferred list), `COINTEGRATION_BASKET_PROMOTION_PLAN_2026-06-07.md` (promotion), `BROKER_EXECUTION_POSTMORTEM_2026_06_06.md` (broker-seam defects). TS_Execution-side memory: `basket-producer-slice-scope`, `basket-demo-observability-plan`.*
