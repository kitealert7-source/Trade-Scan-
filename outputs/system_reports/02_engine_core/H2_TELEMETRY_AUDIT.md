# H2 Basket Telemetry Audit

**Sample basket:** `90_PORT_H2_5M_RECYCLE_S03_V1_P00` (B1 — EUR+JPY @ Gate=5, harvested 302d)
**Backtest dir:** `TradeScan_State/backtests/90_PORT_H2_5M_RECYCLE_S03_V1_P00_H2/`
**Vault dir:** `DRY_RUN_VAULT/baskets/90_PORT_H2_5M_RECYCLE_S03_V1_P00/H2/`
**Generated:** 2026-05-16

**Purpose:** Inventory all emitted telemetry, map against `tools/harvest_robustness/` operator needs, identify gaps, propose minimal additive improvements.

**Hard rule observed:** audit only. No files modified beyond this deliverable.

---

## DECISIONS LOCKED — 2026-05-16 (operator approval)

| # | Item | Status |
|---|---|---|
| 1 | **Schema** — 35 fixed + 8 per-leg columns across 7 blocks (A: Time/identity, B: Equity state, C: Margin/capital, D: Engine control, E: Position state, F: Per-leg state, G: Strategy state). See §"Locked schema" below. | **APPROVED — no changes** |
| 2 | **Format** — Machine → **Parquet** (`results_basket_per_bar.parquet`). Human → **XLSX** (extend `Master_Portfolio_Sheet.xlsx` :: `Baskets` tab with derived summary columns). | **APPROVED — locked** |
| 3 | **Implementation** — Separate session with its own implementation plan doc. Protected Infrastructure patch (`tools/basket_runner.py`, etc.) — do NOT mix with this audit thread. | **APPROVED — defer to new session** |
| 4 | **Backfill of 271 historical baskets** — Deferred. Sequence: implement → run on champions (B1, AUD+JPY, B2) → validate no drift against reconstruction baseline → validate harvest_robustness readers consume the parquet correctly → THEN decide on wider backfill. No compute spent before emitter is proven. | **DEFERRED — gate on implementation validation** |

**Governing format-decision rule (locked, from operator 2026-05-16):**

| Format | Consumer | When to choose |
|---|---|---|
| Parquet / SQL DB | Machine | High-volume time-series |
| CSV | Machine | Small artifacts; also retained for legacy schemas that work well |
| Excel (xlsx) | Human | Derived summary artifacts (sortable in spreadsheet) |
| Markdown | Human | Per-run reports (operators read files directly) |

**This audit is closed.** All further work (implementation plan doc, code patch, validation) belongs in a separate session.

---

## Part 1 — Current Telemetry Inventory

### 1.1 `raw/results_tradelevel.csv`

**Rows:** 32 (= 30 recycle winner-realizations + 2 final harvest closes, one per leg)
**Schema version:** 1.2.0-basket
**Frequency:** per-trade (one row per realized winner event + final harvest exit per leg)

| # | Column | dtype | Populated? | Raw/Derived | Notes |
|---|---|---|---|---|---|
| 1 | `run_id` | object | 32/32 | raw | execution UUID |
| 2 | `strategy_name` | object | 32/32 | raw | basket directive id |
| 3 | `parent_trade_id` | int64 | 32/32 | raw | unique per row |
| 4 | `sequence_index` | int64 | 32/32 | raw | per-leg sequence |
| 5 | `entry_timestamp` | object | 32/32 | raw | UTC, 30 unique (some entry+exit same bar) |
| 6 | `exit_timestamp` | object | 32/32 | raw | UTC |
| 7 | `direction` | int64 | 32/32 | raw | always 1 (long) for this basket |
| 8 | `entry_price` | float64 | 32/32 | raw | leg's weighted avg entry at realization |
| 9 | `exit_price` | float64 | 32/32 | raw | bar close at realization |
| 10 | `pnl_usd` | float64 | 32/32 | derived | (exit-entry) × position × FX-conversion |
| 11 | `r_multiple` | float64 | **0/32 ALL NULL** | n/a | inherited from normal-strategy schema |
| 12 | `trade_high` | float64 | **0/32 ALL NULL** | n/a | inherited |
| 13 | `trade_low` | float64 | **0/32 ALL NULL** | n/a | inherited |
| 14 | `bars_held` | int64 | 32/32 | raw | **0 for recycle winners, >0 for harvest exits** (only signal distinguishing) |
| 15 | `atr_entry` | float64 | **0/32 ALL NULL** | n/a | inherited |
| 16 | `position_units` | float64 | 32/32 | derived | **constant 1000.0** — does NOT reflect loser-leg lot growth (see §3.5 gap) |
| 17 | `notional_usd` | float64 | 32/32 | derived | varies for USD-quote pairs (entry × 1000); constant for USD-base. **Does NOT reflect grown lot.** |
| 18-30 | `mfe_*`, `mae_*`, `volatility_regime`, `trend_*`, `initial_stop_price`, `risk_distance`, `market_regime`, `regime_id`, `regime_age` | mixed | **ALL NULL** | n/a | inherited from normal-strategy schema; not emitted by basket runner |
| 31 | `symbol` | object | 32/32 | raw | leg identifier |

**Missing column that exists in per-leg vault trade_log.csv:** `exit_source` (BASKET_RECYCLE_WINNER vs BASKET_HARVEST_TARGET). Currently `bars_held == 0` is used as proxy.

### 1.2 `raw/results_basket.csv`

**Rows:** 1 (single-row summary)
**Frequency:** final summary

| Column | dtype | Raw/Derived | Notes |
|---|---|---|---|
| `recycle_event_count` | int | raw | count of winner-realize events |
| `harvested_total_usd` | float | raw | cumulative cash banked at harvest (TARGET/FLOOR/TIME/BLOWN) |
| `final_realized_usd` | float | raw | sum of pnl_usd across all per-leg records |
| `exit_reason` | enum | raw | TARGET / FLOOR / BLOWN / TIME / NONE |
| `days_to_exit` | int | derived | calendar days from start_date to last trade exit |

### 1.3 `raw/results_standard.csv`

**Rows:** 1 | **Frequency:** final summary

| Column | dtype | Raw/Derived |
|---|---|---|
| `net_pnl_usd` | float | derived |
| `trade_count` | int | raw |
| `win_rate` | float | derived |
| `profit_factor` | float | derived |
| `gross_profit` | float | derived |
| `gross_loss` | float | derived |

### 1.4 `raw/results_risk.csv`

**Rows:** 1 | **Frequency:** final summary

| Column | dtype | Raw/Derived | ⚠ Caveat |
|---|---|---|---|
| `max_drawdown_usd` | float | derived | **REALIZED equity DD only** ($14 here). NOT intra-bar floating DD ($495 for this basket). |
| `max_drawdown_pct` | float | derived | REALIZED basis |
| `return_dd_ratio` | float | derived | uses realized DD — operator-misleading |
| `sharpe_ratio` | float | derived | from daily realized equity curve |
| `sortino_ratio` | float | derived | from daily realized equity curve |
| `k_ratio` | float | derived | from equity curve slope |
| `sqn` | float | derived | |

### 1.5 `raw/results_yearwise.csv`

**Rows:** 1 per year present | **Frequency:** annual

| Column | dtype | Raw/Derived |
|---|---|---|
| `year` | int | raw |
| `net_pnl_usd` | float | derived |
| `trade_count` | int | raw |
| `win_rate` | float | derived |

### 1.6 `raw/metrics_glossary.csv`

**Rows:** 20 metric definitions | **Frequency:** static (per-run identical)
Contains: metric_key, full_name, definition, unit. Documentation only — no telemetry.

### 1.7 `raw/bar_geometry.json`

```json
{ "median_bar_seconds": 300 }
```
Single value. Useful for inferring TF only.

### 1.8 `metadata/run_metadata.json`

| Key | Value | Notes |
|---|---|---|
| `run_id`, `strategy_name`, `basket_id` | strings | identifiers |
| `execution_mode` | "basket" | distinguisher |
| `leg_symbols` | list | basket composition |
| `timeframe`, `date_range` | strings | execution context |
| `execution_timestamp_utc` | str | provenance |
| `engine_name`, `engine_version` | strings | "1.5.9" |
| `broker` | "OctaFx" | |
| `schema_version` | "1.2.0-basket" | |
| `reference_capital_usd` | 1000.0 | notional stake (NOT real capital) |

### 1.9 `REPORT_<id>.md`

Derived markdown report. Composed from CSVs 1.2–1.5 plus per-leg breakdown computed from tradelevel groupby symbol. **No new telemetry — pure rendering.**

### 1.10 `STRATEGY_CARD.md`

Configuration snapshot. Includes:
- All directive YAML key→value pairs
- Recycle rule params (trigger_usd, add_lot, dd_freeze_frac, margin_freeze_frac, factor_min, leverage, etc.)
- Hypothesis prose
- Test description prose
- Sweep transition note

**No telemetry — pure config persistence.**

### 1.11 DRY_RUN_VAULT — `recycle_events.jsonl` ⭐ richest telemetry source

**Rows:** 30 (one per recycle event) | **Frequency:** per recycle event (not per-bar)

| Field | dtype | Raw/Derived | Notes |
|---|---|---|---|
| `bar_index` | int | raw | engine-internal 5m bar index |
| `bar_ts` | str | raw | UTC bar timestamp |
| `factor_value` | float | raw | USD_SYNTH.compression_5d at this bar |
| `winner_symbol` | str | raw | leg being realized |
| `winner_realized` | float | derived | floating PnL converted to cash on close |
| `winner_old_entry` | float | raw | leg's prior weighted avg entry |
| `winner_new_entry` | float | raw | reset to current bar close |
| `loser_symbol` | str | raw | leg being grown |
| `loser_old_lot` | float | raw | lot before add |
| `loser_new_lot` | float | raw | lot after add |
| `loser_old_avg` | float | raw | weighted avg entry before add |
| `loser_new_avg` | float | raw | weighted avg entry after add |
| `realized_total` | float | derived | cumulative realized cash at this event |
| `floating_total` | float | raw | **AT-EVENT floating PnL across all legs** — used for lower-bound DD probe |
| `equity_before` | float | derived | starting_equity + realized_total + floating_total |

### 1.12 DRY_RUN_VAULT — `basket_meta.json`

Static summary: basket_id, harvested_total_usd, leg_count, leg_symbols, recycle_event_count, rule_name, rule_version, trade_total. **No new telemetry vs results_basket.csv.**

### 1.13 DRY_RUN_VAULT — per-leg `trade_log.csv`

**Rows per leg:** 16 for B1's legs (= 15 recycle winners on that leg + 1 final harvest exit)

| Column | dtype | Raw/Derived | Notes |
|---|---|---|---|
| `entry_index` | int | raw | bar index of entry |
| `exit_index` | int | raw | bar index of exit |
| `direction` | int | raw | 1 = long |
| `entry_price` | float | raw | weighted avg entry |
| `exit_price` | float | raw | close at exit |
| `exit_source` | str | raw | **BASKET_RECYCLE_WINNER vs BASKET_HARVEST_TARGET** — missing from results_tradelevel.csv |
| `exit_reason` | str | raw | "H2_recycle" |
| `pnl_usd` | float | derived | |

### 1.14 DRY_RUN_VAULT — `leg_metadata.yaml` + `basket.yaml`

Config snapshots; no telemetry.

---

## Part 2 — Mapping to Harvest Robustness Needs

### Realized metrics — fully covered

| Need | Source | Status |
|---|---|---|
| Realized PnL | `results_standard.net_pnl_usd`, `results_basket.final_realized_usd` | ✅ |
| Realized DD | `results_risk.max_drawdown_usd` | ✅ (but cosmetic — see floating risk section) |
| Profit factor | `results_standard.profit_factor` | ✅ |
| Recycle count | `results_basket.recycle_event_count` | ✅ |
| Days to harvest | `results_basket.days_to_exit` | ✅ |

### Floating risk — large gap

| Need | Source | Status |
|---|---|---|
| Per-bar floating PnL | NONE | ❌ requires reconstruction (recycle_events + 5m OHLC mark-to-market) |
| Per-bar equity | NONE | ❌ requires reconstruction |
| Per-bar margin used | NONE | ❌ requires reconstruction + per-bar lot timeline (derivable from events but tedious) |
| Per-bar margin level % | NONE | ❌ requires both above |
| Floating DD from peak | NONE | ❌ requires per-bar equity series |
| Floating PnL at events (lower bound) | `recycle_events.floating_total` | ⚠ at-event sparse only |

### Freeze mechanics — ZERO emission

| Need | Source | Status |
|---|---|---|
| dd_freeze event count | rule internal `_n_dd_freezes` (lost on basket close) | ❌ |
| margin_freeze event count | rule internal `_n_margin_freezes` (lost on basket close) | ❌ |
| regime gate block count | rule internal `_n_regime_freezes` (lost on basket close) | ❌ |
| Freeze duration (bars) | NONE — would need per-bar freeze state | ❌ |
| Worst floating during a freeze | NONE | ❌ |

### Composite analysis — partially covered

| Need | Source | Status |
|---|---|---|
| Synchronized timestamps | `recycle_events.bar_ts` + `results_tradelevel.exit_timestamp` | ✅ |
| Cumulative realized equity (per basket) | `cumsum(pnl_usd)` on tradelevel | ✅ (derivable trivially) |
| Floating exposure at each bar | NONE | ❌ same as per-bar floating PnL |

### Capital model — partial

| Need | Source | Status |
|---|---|---|
| Peak lot per leg | `recycle_events.loser_new_lot` max | ⚠ derivable but not emitted to summary |
| Peak notional per leg | Compute: peak_lot × peak_price | ⚠ requires per-bar prices |
| Peak margin per leg | Compute: peak_lot × 100k / leverage | ⚠ requires peak_lot only |

---

## Part 3 — Gap Matrix

| # | Metric | Classification | Where derivable from |
|---|---|---|---|
| 1 | Realized PnL | **PRESENT_DIRECTLY** | `results_standard`, `results_basket` |
| 2 | Realized Max DD | **PRESENT_DIRECTLY** | `results_risk` |
| 3 | Profit factor | **PRESENT_DIRECTLY** | `results_standard` |
| 4 | Recycle count | **PRESENT_DIRECTLY** | `results_basket` |
| 5 | Days to harvest | **PRESENT_DIRECTLY** | `results_basket` |
| 6 | Sharpe / Sortino / SQN | **PRESENT_DIRECTLY** | `results_risk` (caveat: realized basis) |
| 7 | Year-wise PnL | **PRESENT_DIRECTLY** | `results_yearwise` |
| 8 | Per-leg trade count + PnL | **DERIVABLE_WITHOUT_RECONSTRUCTION** | groupby symbol on tradelevel |
| 9 | Cumulative realized equity curve | **DERIVABLE_WITHOUT_RECONSTRUCTION** | `cumsum(tradelevel.pnl_usd)` |
| 10 | Days between recycle events | **DERIVABLE_WITHOUT_RECONSTRUCTION** | diff on `recycle_events.bar_ts` |
| 11 | At-event floating PnL (lower bound DD) | **DERIVABLE_WITHOUT_RECONSTRUCTION** | `recycle_events.floating_total` min |
| 12 | Peak lot per leg | **DERIVABLE_WITHOUT_RECONSTRUCTION** | `max(loser_new_lot for loser=symbol)` |
| 13 | Per-bar floating PnL | **DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION** | recycle_events state timeline + 5m OHLC (~7s per basket via current `h2_intrabar_floating_dd.py`) |
| 14 | Per-bar equity | **DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION** | same as #13 |
| 15 | Per-bar margin used | **DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION** | per-bar lot timeline × 5m close × 100k / leverage |
| 16 | Per-bar margin level % | **DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION** | requires #13 + #15 |
| 17 | Intra-bar Max DD (true) | **DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION** | min(per-bar equity − cummax) |
| 18 | dd_freeze event count | **NOT_AVAILABLE** | tracked but not emitted |
| 19 | margin_freeze event count | **NOT_AVAILABLE** | tracked but not emitted |
| 20 | regime gate block count | **NOT_AVAILABLE** | tracked but not emitted |
| 21 | Freeze duration (bars) | **NOT_AVAILABLE** | no per-bar freeze state recorded |
| 22 | Worst floating during a freeze | **NOT_AVAILABLE** | requires per-bar floating + per-bar freeze state |
| 23 | exit_source per row in main tradelevel | **NOT_AVAILABLE** | present in vault per-leg trade_log only |
| 24 | Per-bar gate-active state | **NOT_AVAILABLE** | factor_value only sampled at events |

**Summary distribution:**
- PRESENT_DIRECTLY: 7
- DERIVABLE_WITHOUT_RECONSTRUCTION: 5
- DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION: 5
- NOT_AVAILABLE: 7

---

## Part 4 — Ranked Improvement Proposals — REVISED 2026-05-16

> **Revision reason — principle compliance.** The original ranking below treated per-bar telemetry as a "big opt-in ask" and recommended summary-only additions as the #1 patch. That was wrong under the established principle:
>
> > **No rerun or source-data reload should ever be required to draw any conclusion or report from metrics captured in backtests.**
>
> The normal robustness suite (`tools/robustness/`) consumes pre-existing `deployable_trade_log.csv` + `equity_curve.csv` + `summary_metrics.json` and runs every analysis (Monte Carlo, bootstrap, tail, rolling, drawdown) without touching source bar data. Current basket artifacts violate this: `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` reloads 5m OHLC and replays state from `recycle_events.jsonl` — a mini-backtest at analysis time.
>
> Equivalent for normal strategies would be: forcing the robustness suite to re-tick the 5m data through the engine just to compute Max DD. Nobody does that, because equity_curve.csv carries per-bar equity directly. Baskets need the analogous artifact.
>
> The revised ranking below puts the per-bar basket state CSV as #1 — it's the **single change that makes the harvest robustness suite self-sufficient under the principle**. Summary-only patches (the previous #1-#4) become optional convenience derivable from the per-bar CSV.

### #1 (NEW) — Emit per-bar basket state ledger `raw/results_basket_per_bar.parquet`

This is the principle-restoring patch. The engine already computes all required values bar-by-bar during the backtest (to evaluate triggers, freezes, and harvest condition). We just need to persist what's already in memory.

**Required schema (~9 columns, satisfies all DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION + NOT_AVAILABLE gaps in §3):**

| Column | dtype | Source | Why required |
|---|---|---|---|
| `bar_ts` | datetime | engine clock | timestamp axis; enables composite synchronization |
| `realized_cum_usd` | float | sum of winner_realized for all events ≤ this bar | derives realized equity curve |
| `floating_total_usd` | float | engine's per-bar floating PnL across all legs (already computed for trigger check) | THE missing data — eliminates 5m reload |
| `equity_usd` | float | = initial_stake + realized_cum + floating_total | enables intra-bar Max DD computation |
| `margin_used_usd` | float | sum(leg.lot × bar_close × 100k / leverage) | enables margin level % computation |
| `dd_freeze_active` | bool | `dd_breach` condition from rule (line 199 in h2_recycle.py) | freeze duration + worst-floating-during-freeze |
| `margin_freeze_active` | bool | `margin_breach` condition (line 200) | freeze duration |
| `regime_freeze_active` | bool | `factor_val < factor_min` condition (line 216) | gate-active timeline |
| `gate_factor_value` | float | `USD_SYNTH.compression_5d` reading at this bar | gate-active % computation |

**Optional supplementary columns** (Phase 2 if attribution becomes useful):
- per-leg `lot_<symbol>`, `avg_entry_<symbol>`, `floating_<symbol>_usd`
- bar OHLC for the per-leg view

**Operator value:** ⭐⭐⭐⭐⭐ — collapses 5 DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION gaps + 6 NOT_AVAILABLE gaps in §3 to PRESENT_DIRECTLY. Restores principle compliance. Makes composite analysis instantaneous (~1s vs current 7s/basket reconstruction).

**Implementation:** MEDIUM but minimal scope — basket runner already has all 9 values in memory at each bar (floating_total is computed every bar to evaluate trigger; freeze states are evaluated every bar; margin is computed for the margin_breach check). Just persist them. Estimated ~30-line patch:
- Add per-bar emit loop in `BasketRunner.run()` to accumulate rows
- Write CSV at basket close alongside existing `results_basket.csv`
- No new computation; only persistence of values already in memory

**Storage cost:** ~10 MB per basket (~100K rows × ~100 bytes/row for ~1y 5m). Across 271 existing backtests = ~2.7 GB if backfilled (probably not worth backfilling; future-only is fine). Per future basket = ~10 MB — same order as normal-strategy `equity_curve.csv`.

**Risk:** zero — new artifact, no impact on existing readers. Existing harvest robustness modules continue working with old basket runs that lack this file; new modules can prefer it when present.

**Principle parity check:**

| Normal strategy artifact | Basket equivalent (after this patch) |
|---|---|
| `deployable_trade_log.csv` | `results_tradelevel.csv` (already present) |
| `equity_curve.csv` (per-bar equity) | `results_basket_per_bar.parquet` (per-bar equity + extras) — **new** |
| `summary_metrics.json` | `results_basket.csv` + `results_standard.csv` + `results_risk.csv` (already present, slim) |

### #2 — Add freeze counters to `results_basket.csv`

**New columns:** `dd_freeze_count` (int), `margin_freeze_count` (int), `regime_freeze_count` (int)
**Operator value:** ⭐⭐⭐⭐⭐ — directly resolves the §4.15a operator question ("did the freeze fire? how often?"). Currently invisible. The freeze mechanism is the strategy's primary defensive control; we have no post-run evidence that it engaged.
**Implementation:** TRIVIAL — `H2RecycleRule._n_dd_freezes`, `_n_margin_freezes`, `_n_regime_freezes` already track these. Just emit at basket close. ~5-line patch to `basket_report.py` or whoever writes results_basket.csv.
**Storage:** 3 ints × 1 row = ~12 bytes per basket
**Risk:** zero — pure additive columns, no consumer breakage.

### #3 — Add peak-lot per leg to `results_basket.csv`

**New columns:** `peak_lot_<symbol>` per leg (e.g., `peak_lot_EURUSD`, `peak_lot_USDJPY`)
**Operator value:** ⭐⭐⭐⭐ — answers "what's the worst-case capital tied up?" for margin planning. Currently invisible in tradelevel (position_units stuck at 1000.0 base). Recoverable from `recycle_events.loser_new_lot` but not at-a-glance.
**Implementation:** TRIVIAL — derive from internal leg state at close or aggregate over recycle events. ~5-line patch.
**Storage:** N floats per basket (N = leg count, typically 2)
**Risk:** zero — pure additive columns.

### #4 — Add `exit_source` to `results_tradelevel.csv`

**New column:** `exit_source` (str: `BASKET_RECYCLE_WINNER` or `BASKET_HARVEST_TARGET`)
**Operator value:** ⭐⭐⭐ — currently `bars_held == 0` is used as a proxy in the harvest robustness modules. Fragile (what if a future basket has a same-bar harvest?). Per-leg vault `trade_log.csv` already has this column; main tradelevel doesn't.
**Implementation:** SIMPLE — already known at write-time. ~3-line patch.
**Storage:** ~25 bytes × 32 rows = ~800 bytes per basket.
**Risk:** zero — additive column, consumers ignore unknown columns.

### #5 — Add `worst_floating_at_event_usd` and `peak_realized_usd` to `results_basket.csv`

(Note: with #1 in place, these become trivially derivable from the per-bar CSV — `min(floating_total_usd)` and `max(realized_cum_usd)`. Adding them as summary columns is still a nice at-a-glance convenience but is no longer principle-critical.)

**New columns:** `worst_floating_at_event_usd` (float), `peak_realized_usd` (float)
**Operator value:** ⭐⭐⭐ — lower-bound on intra-bar floating DD (without needing 5m reconstruction). Peak realized is the highwater mark for realized equity.
**Implementation:** TRIVIAL — aggregate over `recycle_events.jsonl` at write time. ~5-line patch.
**Storage:** 2 floats × 1 row = ~16 bytes per basket
**Risk:** zero.

---

## FINAL RECOMMENDATION — REVISED 2026-05-16 (v2): Canonical Basket State Ledger

> **Reframe from operator (2026-05-16):** patching telemetry later creates three structural problems:
> 1. **Historical incompatibility** — old runs miss fields
> 2. **Forced reruns** — exactly what the principle prohibits
> 3. **Research bias** — future questions become constrained by what was logged
>
> **Therefore: over-capturing telemetry is cheaper than under-capturing. Capture generously NOW, lock the schema, never need to come back.**
>
> Architectural framing: **not a "per-bar DD CSV". A permanent basket flight recorder.** Same role as aircraft telemetry — record everything happening at every bar so any future question can be answered by querying the ledger, never by replaying. When research moves from FX → metals → crypto, from 2-leg → 5-leg → portfolio, the ledger has already captured what's needed.
>
> This supersedes the v1 recommendation (narrow 9-column per-bar CSV) below. Both are preserved in this doc — v1 as the under-capture floor, v2 as the locked design.

### Locked schema — `raw/results_basket_per_bar.parquet`

Every column captured at every 5m bar from basket open to basket exit, append-only.
(File format updated 2026-05-16: parquet, following the system's existing high-volume telemetry convention — see "Recommended storage format" below.)

#### Block A — Time / identity (never changes across asset classes)

| Column | dtype | Source | Notes |
|---|---|---|---|
| `timestamp` | datetime (UTC) | engine clock | bar timestamp |
| `directive_id` | str | directive name | enables cross-basket join with tradelevel |
| `basket_id` | str | basket config | typically "H2" today; varies in future basket types |
| `bar_index` | int | engine-internal | matches `recycle_events.bar_index` for event correlation |
| `run_id` | str | execution UUID | matches run_metadata.json, enables ledger ↔ run-registry join |

#### Block B — Equity state (operator truth)

| Column | dtype | Notes |
|---|---|---|
| `floating_total_usd` | float | basket-level mark-to-market PnL across all legs at this bar |
| `realized_total_usd` | float | cumulative cash banked from all recycle winner events ≤ this bar |
| `equity_total_usd` | float | = `initial_stake_usd + realized_total_usd + floating_total_usd` |
| `peak_equity_usd` | float | running cummax of `equity_total_usd` from basket open to this bar |
| `dd_from_peak_usd` | float | = `equity_total_usd - peak_equity_usd` (≤ 0, magnitude = drawdown depth) |
| `dd_from_peak_pct` | float | = `dd_from_peak_usd / peak_equity_usd × 100` |

#### Block C — Margin / capital state (live survivability)

| Column | dtype | Notes |
|---|---|---|
| `margin_used_usd` | float | sum across legs: `lot × bar_close × 100k / leverage`. Real-time margin draw. |
| `free_margin_usd` | float | = `equity_total_usd - margin_used_usd`. Operator's working buffer. |
| `margin_level_pct` | float | = `equity_total_usd / margin_used_usd × 100`. Broker margin-call distance. |
| `notional_total_usd` | float | sum across legs: `lot × bar_close × 100k`. Total exposed notional. |
| `leverage_effective` | float | engine-config leverage (1000 for OctaFx FX; varies for crypto/metals). Per-bar capture allows asset-class generalization without schema change. |

#### Block D — Engine control state (the **why** of every bar)

| Column | dtype | Notes |
|---|---|---|
| `dd_freeze_active` | bool | `dd_breach` condition held this bar (`abs(floating_total) >= dd_freeze_frac × equity`) |
| `margin_freeze_active` | bool | `margin_breach` condition held this bar |
| `regime_gate_blocked` | bool | `factor_val < factor_min` this bar (gate-active = False) |
| `recycle_attempted` | bool | rule's `apply()` was entered this bar |
| `recycle_executed` | bool | recycle action committed (winner realized, loser grew) |
| `harvest_triggered` | bool | `equity_total_usd >= harvest_target_usd` this bar (basket closes after) |
| `engine_paused` | bool | external engine-level pause (gap halt, market close, future use) |
| `skip_reason` | str enum | why no recycle fired this bar (see enum below) |

**`skip_reason` enum values** (covers every early-return path in `h2_recycle.py:apply()`):
- `NONE` — recycle attempted and executed
- `HARVESTED` — basket already harvested; rule short-circuits
- `DD_FREEZE` — `dd_breach` blocked
- `MARGIN_FREEZE` — `margin_breach` blocked
- `REGIME_GATE` — factor below min
- `NO_WINNER` — no leg met `trigger_usd` floating threshold
- `NO_LOSER` — no opposite leg in floating loss
- `PROJECTED_MARGIN_BREACH` — post-recycle projected margin would breach
- `RULE_NOT_INVOKED` — engine didn't call apply() this bar (e.g., bar gap, missing data)

#### Block E — Position state (basket level, N-leg-generic)

| Column | dtype | Notes |
|---|---|---|
| `active_legs` | int | count of legs with `lot > 0` |
| `total_lot` | float | sum of all leg lots (a measure of total position size) |
| `largest_leg_lot` | float | max(lot across legs) — identifies the currently-grown loser |
| `smallest_leg_lot` | float | min(lot across legs) — typically the recently-realized winner at base lot |

#### Block F — Per-leg state (dynamic, wide format `leg_<i>_*`)

For each leg `i` from 0 to `basket.leg_count - 1`:

| Column pattern | dtype | Notes |
|---|---|---|
| `leg_<i>_symbol` | str | leg's instrument (e.g., "EURUSD") |
| `leg_<i>_side` | str | "long" or "short" (always "long" for H2 today, kept for future flexibility) |
| `leg_<i>_lot` | float | current lot size (changes when loser grows or winner realizes) |
| `leg_<i>_avg_entry` | float | weighted average entry price |
| `leg_<i>_mark` | float | bar close — the price used for mark-to-market |
| `leg_<i>_floating_usd` | float | this leg's contribution to `floating_total_usd` |
| `leg_<i>_margin_usd` | float | this leg's contribution to `margin_used_usd` |
| `leg_<i>_notional_usd` | float | this leg's contribution to `notional_total_usd` |

**Why wide format `leg_<i>_*` instead of long-format separate ledger file:**
- Self-contained per-basket: one CSV, one read, all columns aligned on `timestamp`
- Column count = `leg_count × 8` (16 for 2-leg, 32 for 4-leg, 48 for 6-leg) — manageable
- Cross-basket queries with mixed leg counts: union the columns, NaN-fill missing — pandas handles natively
- Long format would be a 2nd file requiring a join — adds analysis friction without storage savings

#### Block G — Strategy-state telemetry (the "context" most people forget)

| Column | dtype | Notes |
|---|---|---|
| `recycle_count` | int | cumulative number of recycle events from basket open to this bar |
| `bars_since_last_recycle` | int | bars since the most recent `recycle_executed = True` event (0 = recycle this bar; null until first recycle) |
| `bars_since_last_harvest` | int | bars since basket-open or most recent harvest (relevant if future basket types support multi-harvest cycles); for single-cycle H2 = bars since open |
| `gate_factor_value` | float | the regime factor reading at this bar (`USD_SYNTH.compression_5d` for H2; future strategies may use different factors — captured by name) |
| `gate_factor_name` | str | identifier of the gate factor in use (e.g., "USD_SYNTH.compression_5d") — explicit for future multi-factor strategies |
| `winner_leg_idx` | int (nullable) | when `recycle_executed`, the leg index of the realized winner; else null |
| `loser_leg_idx` | int (nullable) | when `recycle_executed`, the leg index of the grown loser; else null |

---

### Total column count and storage estimate — REVISED 2026-05-16

> **Revision context (operator challenge):** original v2 estimate assumed CSV uncompressed at ~12 bytes/col × 100K rows = ~60 MB/basket. Empirical check against normal-strategy artifacts revealed the assumption was off — bytes/col is actually closer to 14 (from `deployable_trade_log.csv` at 17 cols / 553 KB / 2326 rows = 238 bytes/row ≈ 14 bytes/col), bars/year-of-5m-basket is ~62K not 100K (FX 5m has ~71% market-open coverage), and CSV-uncompressed is not the only format option. Corrected below.

| Block | Columns (per row) | Notes |
|---|---|---|
| A — Time/identity | 5 | constant |
| B — Equity state | 6 | constant |
| C — Margin/capital | 5 | constant |
| D — Engine control | 8 | constant |
| E — Position state (basket) | 4 | constant |
| F — Per-leg state | 8 × N (16 for 2-leg, 48 for 6-leg) | scales with leg count |
| G — Strategy state | 7 | constant |
| **Total** | **35 + 8N** (51 for 2-leg, 83 for 6-leg) | |

**Bars per basket** (5m FX, ~71% market-open coverage):
- 302-day cycle (B1): ~62,000 bars
- 591-day cycle (B2, AUD+CAD): ~122,000 bars
- Typical mix: ~80,000 bars average

**Storage per basket, three formats:**

| Format | 2-leg basket (~80K bars × 51 cols) | 4-leg basket (~80K × 67) | 6-leg basket (~80K × 83) | Notes |
|---|---|---|---|---|
| CSV uncompressed | ~45 MB | ~60 MB | ~80 MB | matches normal-strategy text convention; grep-friendly |
| **Gzipped CSV** (`.csv.gz`) | **~5–8 MB** | ~8–12 MB | ~10–14 MB | pandas reads transparently (`pd.read_csv(path)` auto-detects gz); 85% compression because `directive_id`, `run_id`, leg symbols/sides repeat 80K times |
| Parquet (`.parquet`) | ~3–5 MB | ~5–8 MB | ~6–10 MB | columnar compression; even faster reads; adds pyarrow dependency |

**Comparison with normal-strategy artifacts (empirically measured 2026-05-16):**

| Strategy type | Artifact | Cols | Rows | Bytes | Rationale |
|---|---|---|---|---|---|
| Normal FX 1H | `equity_curve.csv` | 2 | 4651 | 167 KB | per-TRADE (one row per trade entry + exit); position flat between trades |
| Normal FX 1H | `deployable_trade_log.csv` | 17 | 2326 | 553 KB | per-trade |
| Normal FX 1H | summary_metrics.json | — | — | 0.6 KB | single-shot |
| **Normal total per profile** | | | | **~720 KB** | |
| **Basket 5m (proposed)** | `results_basket_per_bar.parquet` | 51 | ~80K | **~3-5 MB parquet** | per-BAR (basket continuously open; floating PnL changes every bar) |

**Why baskets are structurally ~30-60× larger than normal strategies** (irreducible):
- Normal strategies are flat between trades → per-trade emission captures all state
- Baskets are continuously open from open to harvest → floating PnL changes every bar → per-bar emission is the minimum cadence that preserves DD/freeze information
- The 30-60× row-count multiplier is intrinsic to the strategy type, not a design choice

**Across the current 271 backtests (if backfilled):**
- CSV uncompressed: ~12 GB
- **Gzipped CSV: ~1.5 GB**
- Parquet: ~1 GB

**Future-only at current research cadence (~50-100 baskets/month during active phases):**
- CSV uncompressed: ~3-6 GB/year
- **Gzipped CSV: ~400-800 MB/year**
- Parquet: ~250-500 MB/year

**For perspective:**
- `data_root/MASTER_DATA/` USD 5m source data: ~4 GB
- Gzipped backfill ledger: ~1.5 GB (40% of source data; the ledger captures the strategy's *reaction* to every bar of source data, so this ratio is structurally reasonable)
- Existing 271 backtest artifact dirs combined: probably ~few hundred MB (currently sparse — exactly the gap this patch fills)

### Recommended storage format — REVISED 2026-05-16: Parquet

> **Governing principle (operator, 2026-05-16):**
>
> | Format | Consumer | When to choose |
> |---|---|---|
> | **Parquet** / **SQL DB** | Machine (engines, analysis tools, pipelines) | High-volume time-series — chosen for typed schemas, columnar reads, compression |
> | **CSV** | Machine | Small artifacts where size doesn't force the parquet upgrade — used selectively; also retained for legacy schemas that predate parquet adoption and work well as-is |
> | **Excel** (.xlsx) | Human (operator review, decision-making) | Derived summary artifacts — sortable, filterable in a spreadsheet |
> | Markdown | Human | Per-run reports (`REPORT_*.md`, `STRATEGY_CARD.md`) — operators read files directly |
>
> Examples in the current system:
> - Machine + parquet: `.cache/ohlc_cache/*.parquet` (15K files), regime cache, future basket ledger
> - Machine + SQL: `tools/ledger_db.py` SQLite (single-source-of-truth for MPS rows)
> - Machine + CSV (legacy / small): `results_tradelevel.csv`, `equity_curve.csv`, `deployable_trade_log.csv`, `results_*.csv` summaries — pre-date parquet adoption, work well at their scale, no migration needed
> - Human + Excel: `Master_Portfolio_Sheet.xlsx`, `Strategy_Master_Filter.xlsx`
> - Human + Markdown: `REPORT_*.md`, `STRATEGY_CARD.md`
>
> **Where the basket ledger fits:** machine-consumed, high-volume (80K × 51 cols per basket) — falls cleanly in the parquet bucket. Size makes the upgrade worth it; legacy small-CSV bucket isn't appropriate here.
>
> **Where the human view of the ledger lives:** derived summary rows in `Master_Portfolio_Sheet.xlsx` :: `Baskets` sheet (one row per basket, sortable in spreadsheet).
>
> The v2 recommendation initially defaulted to gzipped CSV by pattern-matching against the `results_*.csv` neighbor files in the `raw/` directory. Those neighbors are small (~5 KB to ~7 KB each) — appropriate for CSV. The basket ledger at 80K rows is in a different size class entirely and follows the parquet path used by the OHLC cache.

**Ship as parquet (`results_basket_per_bar.parquet`).**

**Existing convention this aligns with:**

| Where parquet is the standard | Why |
|---|---|
| `.cache/ohlc_cache/*.parquet` (15,532 files) | Per-symbol bar-level OHLC cache |
| `.cache/regime_cache/*.parquet` | Pre-computed regime state |
| `engines/regime_state_machine.py` lines 197 + 386 | Reads & writes parquet for runtime regime computation |

**Where CSV is the standard:**

| Artifact class | Why |
|---|---|
| `results_*.csv`, `equity_curve.csv`, `deployable_trade_log.csv` | Small summary / per-trade artifacts (rows in 10s-1000s); human-readable / grep-friendly |
| `summary_metrics.json`, `run_metadata.json` | Single-shot config-like blobs |

The basket ledger matches the high-volume engine-telemetry profile (parquet), not the small summary profile (CSV).

**Reasons parquet is correct here:**

1. **Convention match.** The OHLC cache and the basket ledger are the same artifact class — high-volume, engine-emitted, typed time-series. The patch aligns with how the system already handles this data shape.

2. **Pyarrow already a hard dependency.** `engines/regime_state_machine.py` calls `pd.read_parquet`/`to_parquet` at runtime. Adding parquet emission elsewhere is zero new dependency footprint.

3. **Schema-typed beats stringly-typed.** CSV reads coerce everything through pandas type inference at load time — fragile for booleans (`dd_freeze_active`) and enums (`skip_reason`). Parquet writes column types into the file; reads get back the same types. Eliminates a class of subtle dtype drift bugs in downstream consumers.

4. **Storage efficiency.** ~3-5 MB per basket vs ~5-8 MB gzipped CSV vs ~45 MB raw CSV. ~1 GB total for 271-backtest backfill. ~250-500 MB/year future-only.

5. **Columnar reads.** `pd.read_parquet(path, columns=["equity_total_usd", "timestamp"])` loads only those columns — ~10× faster than full CSV load when analytical queries touch a subset (which most harvest_robustness modules do).

6. **Predicate pushdown.** Date-range filters can apply during read, not after load. Speeds up window-specific analyses (e.g., "show me the freeze events during Q4 2025").

7. **Self-describing.** The parquet file carries its own schema metadata. Eliminates documentation drift between this audit and the actual emitted columns.

**Note on the `read_parquet` FORBIDDEN_ATTRS in `tools/semantic_validator.py`:** that rule applies to **strategy code** (the strategy.py file the engine executes per-bar — strategies must not read external data, only consume engine-provided indicators). It does NOT apply to analysis tools or basket-runner artifacts. The harvest_robustness modules are analysis tools, not strategy code, and `engines/regime_state_machine.py` is an engine module — both legitimate parquet consumers/producers.

**Storage table (revised primary recommendation):**

| Format | 2-leg basket | 4-leg basket | 6-leg basket | 271-basket backfill | Per year future |
|---|---|---|---|---|---|
| **Parquet (recommended, machine)** | **~3-5 MB** | ~5-8 MB | ~6-10 MB | **~1 GB** | **~250-500 MB** |
| Gzipped CSV (rejected — wrong consumer) | ~5-8 MB | ~8-12 MB | ~10-14 MB | ~1.5 GB | ~400-800 MB |
| CSV uncompressed (rejected — wrong consumer) | ~45 MB | ~60 MB | ~80 MB | ~12 GB | ~3-6 GB |

### Human-facing companion artifact — Master Portfolio Sheet (Baskets tab)

Under the format-follows-consumer principle, the parquet ledger is the **machine** artifact. The **human** companion is a row-per-basket summary in `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx` :: `Baskets` sheet, where one row per dispatched basket directive already exists today.

This sheet should grow new columns derived from the parquet ledger at basket-close time:

| New column (proposed) | Derived from ledger |
|---|---|
| `peak_floating_dd_usd` | `-min(dd_from_peak_usd)` over the lifetime |
| `peak_floating_dd_pct` | `-min(dd_from_peak_pct)` |
| `dd_freeze_count` | count of `dd_freeze_active` transitions false→true |
| `margin_freeze_count` | count of `margin_freeze_active` transitions |
| `regime_freeze_count` | count of `regime_gate_blocked` transitions |
| `peak_lot_<symbol>` per leg | max of `leg_<i>_lot` for each leg |
| `peak_margin_used_usd` | max of `margin_used_usd` |
| `min_margin_level_pct` | min of `margin_level_pct` (operator's broker-margin-call distance) |
| `worst_floating_at_freeze_usd` | min of `floating_total_usd` while any freeze flag was active |
| `return_on_real_capital_pct` | `final_pnl_usd / (2 × peak_floating_dd_usd)` — capital-efficient return metric |

Producer/consumer chain:
1. **Basket runner** writes per-bar state → `results_basket_per_bar.parquet` (machine, the source of truth)
2. **Basket report writer / ledger appender** reads the parquet at basket close, computes summary stats, appends row to `Master_Portfolio_Sheet.xlsx` Baskets tab (human, for review)
3. **Harvest robustness modules** read the parquet (machine, for analyses requiring full timeline)

This keeps the parquet authoritative (single source of truth, all derivations reproducible) and the Excel view operator-friendly (one row per basket, sortable, reviewable in a spreadsheet without ever opening the parquet).

### Why this satisfies the principle PERMANENTLY

Every future research question this audit can imagine (and a long tail it can't) is now answerable from CSV reads:

| Future question | Answer mechanism |
|---|---|
| "Intra-bar Max DD on basket X" | `min(dd_from_peak_usd)` — Block B |
| "Worst margin level reached" | `min(margin_level_pct)` — Block C |
| "How many bars did the basket sit in dd_freeze?" | `sum(dd_freeze_active)` — Block D |
| "What was the floating PnL the moment the dd_freeze first fired?" | filter `dd_freeze_active==True`, take first row's `floating_total_usd` — Block B+D |
| "Did the gate ever save us from a blow-up that would have happened?" | join `regime_gate_blocked` with subsequent reverted adverse move — Block D + B |
| "Which leg dominated the worst DD?" | sort by `dd_from_peak_usd`, inspect `leg_*_floating_usd` at that bar — Block B+F |
| "Average bars between recycle events" | diff of `recycle_count` change points — Block G |
| "What's the largest lot we held on any leg in any basket?" | `max(largest_leg_lot)` over the union — Block E |
| "How does recycle frequency vary with gate factor value?" | groupby `gate_factor_value` buckets, count `recycle_executed=True` — Block D+G |
| "Composite intra-bar Max DD across N baskets" | sum per-basket `equity_total_usd` on synchronized timestamps, recompute Max DD — Block A+B |
| "Did the basket nearly margin-call during the Brexit window?" | filter by date range, `min(margin_level_pct)` — Block A+C |
| "When freeze fires, how often does price revert vs continue trending?" | look at subsequent N bars' `floating_total_usd` post-freeze-onset — Block B+D over time |
| Future: "How does this strategy perform on metals?" | leverage_effective captures asset-class diff; per-leg blocks support arbitrary symbol — Block C+F |
| Future: "Compare 2-leg vs 5-leg basket variants" | per-leg dynamic columns scale automatically — Block F |

**Critically: every one of the above requires no 5m data reload, no engine rerun, no analysis-time state replay. Pure CSV reads. This is the principle restored.**

### Migration & rollout

**For new basket runs (default):** emit `results_basket_per_bar.parquet` from basket open. Schema-validated at write time against this spec.

**For the existing 271 backtests:** two-track:
- Track A — **backfill via batch rerun.** Run `tools/run_pipeline.py --all` on the 271 directives in the completed/ folder. ~25-min pipeline time. Produces the ledger for every historical basket. Recommended IF research will reference historical runs heavily.
- Track B — **fallback module retained.** Keep `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` as the legacy-run fallback. New modules prefer the ledger when present; fall back to reload+replay for pre-ledger runs.

Recommend doing **both**: ship the ledger emitter as default for new runs, AND run the backfill batch in a low-priority background window. Track B (fallback) covers the gap during backfill.

### Implementation surface (for later, not now)

This is documentation-only at this stage. When implementation lands, the touch surface is:

1. `tools/basket_runner.py` (or `tools/recycle_rules/h2_recycle.py` apply()) — add per-bar accumulator that records all 35+8N values at every bar
2. `tools/basket_report.py` (or `tools/portfolio/basket_ledger_writer.py`) — write `results_basket_per_bar.parquet` at basket close (machine artifact) AND append summary row to `Master_Portfolio_Sheet.xlsx` Baskets tab with derived columns (human artifact)
3. `tools/recycle_rules/h2_recycle.py` apply() — augment early-return paths to record the correct `skip_reason` enum value
4. `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` — once ledger is available, refactor to prefer the parquet (10-line read) over the 280-line reconstruction (kept as fallback for legacy runs)
5. `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` (LOCKED v11) — add the ledger schema as an officially-locked basket artifact; bump basket schema_version from `1.2.0-basket` → `1.3.0-basket`. Codify the format-follows-consumer principle if not already explicit elsewhere.

Estimated patch size: ~80-120 lines of pure persistence (no new logic, since the engine already computes every value in the schema at trigger-evaluation time). Plus ~30 lines for the human-facing summary row generation against the Master Portfolio Sheet.

### Sequencing recommendation

1. **Now (this deliverable):** the audit doc with this schema locked. Done.
2. **Next session (if approved):** implement the ledger emit (~120-line patch); ship as default.
3. **Backfill (background):** rerun the 271 completed basket directives to backfill historical ledgers (~25 min pipeline).
4. **Harvest robustness refactor:** swap `h2_intrabar_floating_dd.py` to prefer the ledger; add new modules (freeze_analysis, gate_telemetry, leg_attribution) as one-liner readers over the ledger.

---

## v1 — Previous narrow recommendation (superseded by v2 above)

> _Preserved as historical context — this was the narrow 9-column version. v2 above expanded it to the canonical 35+8N ledger after the operator's "over-capture now" reframe._

**Recommended single patch (v1, superseded): Emit `raw/results_basket_per_bar.csv` with the 9-column schema in proposal #1.**

| Column | dtype | Source |
|---|---|---|
| `bar_ts` | datetime | engine clock |
| `realized_cum_usd` | float | rolling sum of `winner_realized` |
| `floating_total_usd` | float | already computed every bar for trigger evaluation |
| `equity_usd` | float | `= initial_stake + realized_cum + floating_total` |
| `margin_used_usd` | float | already computed every bar for margin_breach check |
| `dd_freeze_active` | bool | `dd_breach` condition |
| `margin_freeze_active` | bool | `margin_breach` condition |
| `regime_freeze_active` | bool | `factor < factor_min` condition |
| `gate_factor_value` | float | `USD_SYNTH.compression_5d` per-bar reading |

**Why this is the one patch (under the principle):**

1. **Restores principle compliance.** Without this CSV, the harvest robustness suite is structurally forced to reload 5m OHLC and replay state — equivalent to forcing the normal robustness suite to re-tick the engine. The principle says no.

2. **Collapses 11 gap-matrix rows.** Rows 13–17 (DERIVABLE_WITH_EXPENSIVE_RECONSTRUCTION) + rows 18–22, 24 (NOT_AVAILABLE) all become PRESENT_DIRECTLY. The summary patches #2-#5 become derivable trivially.

3. **Zero new computation.** The basket runner ALREADY computes every value in the schema at every bar — to evaluate triggers, freezes, and the harvest condition. The patch is pure persistence of values already in memory, not new analytics.

4. **Brings baskets to artifact parity with normal strategies.** Normal strategies emit per-bar `equity_curve.csv`. Baskets currently don't. This patch closes that gap symmetrically.

5. **Eliminates the 7-sec-per-basket reconstruction** in `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py`. Composite analysis across 10 baskets goes from ~70s + 5m data load to ~1s pure CSV reads.

**Estimated implementation:** ~30-line patch in `BasketRunner.run()` (or wherever the per-bar trigger evaluation loop lives) to accumulate a list of dicts at each bar, plus a CSV-write at basket close. No new engine-side computation; only persistence.

**Storage cost:** ~10 MB per basket (~100K bars × ~100 bytes). Across future runs at current rate (~50-100 baskets/month during active research, fewer during deployment) = ~1 GB/year — acceptable. Existing 271 backtests cannot be backfilled without rerun; treat as future-only.

**Risk:** zero — new artifact, doesn't change any existing schema. Existing harvest robustness modules (which currently rely on 5m reload) continue working unmodified; new modules can prefer the per-bar CSV when present, falling back to reload for legacy basket runs.

**What this enables in the harvest robustness suite (post-patch):**

- `h2_intrabar_floating_dd.py` becomes a 10-line script that reads the CSV (vs the current ~280-line state-replay implementation)
- A new `freeze_analysis` module becomes trivial (count + duration + worst-floating-during-freeze, all from per-bar bool columns)
- A new `gate_telemetry` module becomes trivial (gate-active % = mean of `regime_freeze_active == False`, gate transitions = state changes)
- Composite analysis becomes a sum-of-equity-series across baskets at synchronized timestamps — no reload, no replay

**Phase 2 follow-up patches** (do AFTER #1, not instead):

- #2 (freeze counters in `results_basket.csv`) — at-a-glance summary; derivable from per-bar but a 1-row summary is friendlier for ledger views and ranking tables
- #3 (peak_lot per leg) — same rationale; derivable but useful at-a-glance
- #4 (`exit_source` on tradelevel) — eliminates the `bars_held == 0` proxy; independent of per-bar CSV
- #5 (`worst_floating_at_event_usd`, `peak_realized_usd`) — derivable from per-bar; nice-to-have

These are all small, additive, and non-blocking. They can ship together with #1 or independently afterward.

**Migration note for existing backtests:** the 271 already-completed basket runs lack this CSV. Two options:
- (a) Backfill via dedicated rerun batch (one-time cost, ~25 minutes pipeline time)
- (b) Keep existing reconstruction module (`h2_intrabar_floating_dd.py`) as the fallback path for legacy runs; new runs use the CSV
- Recommend (b) — backfilling is a separate decision and doesn't block landing the patch

---

## Appendix — Files referenced

- `tools/recycle_rules/h2_recycle.py` lines 197–206 (freeze trigger logic, freeze counters internal state)
- `tools/recycle_rules/h2_recycle.py` lines 134–136 (freeze counter declarations)
- `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` (current expensive reconstruction implementation)
- `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` (LOCKED v11 — schema authority for basket artifacts)
- `research/FX_BASKET_RECYCLE_RESEARCH.md` §3.7, §4.13, §4.15a, §4.15b (operator-facing capital + freeze findings that motivate this audit)
