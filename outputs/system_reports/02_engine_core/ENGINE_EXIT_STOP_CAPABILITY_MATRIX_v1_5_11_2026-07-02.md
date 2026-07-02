# Engine Exit/Stop Capability Matrix — v1.5.11

**Purpose:** triage a hypothesis's exit/stop requirements against what the engine
can actually do *today*, so a directive is correctly classified as
`rule_build_required: true` (buildable in strategy logic) vs
**`engine enhancement required`** (needs new engine code) BEFORE it is tested.
Faithful classification matters because the two blocking mechanisms below
(`partial_taken` lock + monotone stop gate) **fail closed** — an over-reaching
exit spec is silently under-modelled rather than erroring, so the backtest would
answer a different question than the hypothesis asked.

**Scope:** the v1.5.11 execution loop exit/stop machinery. Verified 2026-07-02
against source (not memory). Distinctions:
- **Native** — first-class engine capability.
- **Emulated** — achievable through strategy logic (a hook recomputed each bar);
  engine-facilitated but strategy-authored.
- **Not supported** — would require engine development (a new versioned engine).

> Terminology note: the engine files carry `engine_version = "1.5.11"` in code;
> `contract.json` still stamps `engine_version: v1_5_10` (Patch A core is
> byte-identical to v1.5.10 — the contract was not re-stamped). Both refer to the
> current canonical engine.

---

## Matrix

| Feature | Native | Emulated | Not Supported | Notes |
|---|:---:|:---:|:---:|---|
| Partial close | ✅ *(single)* | | | `check_partial_exit` hook; fires **at most once per trade** |
| Break-even stop move | | ✅ | | No BE primitive; strategy returns `entry_price` from `check_stop_mutation`. Engine exposes `ctx.entry_price` + `ctx.unrealized_r_intrabar` *specifically to enable this* |
| ATR trailing stop | | ✅ | | No trailing primitive; strategy recomputes an ATR stop each bar via `check_stop_mutation` |
| Dynamic stop modification | ✅ *(constrained)* | | | `check_stop_mutation` hook — but **monotone-only** (tighten), applies **from next bar** |
| Multiple simultaneous exit orders | ◐ *(SL+TP only)* | | ✗ *(>2 / laddered)* | Native **1 stop + 1 TP** bracket held at once; no multiple/laddered targets |
| One-cancels-other (OCO) | ✅ *(implicit)* | | | The SL/TP bracket **is** an OCO — first-touch closes the trade; SL wins on a same-bar tie |
| Scale-out + trailing interaction | | ✅ | | Single partial + monotone trail coexist in one bar (ordering steps 2→3); no multi-level ladder |

Legend: ✅ full · ◐ partial/limited · ✗ explicitly absent.

---

## Exact engine locations

All paths under `engine_dev/universal_research_engine/v1_5_11/`.

### Bracket exit resolver (SL+TP, OCO)
- `execution_loop.py:153` `resolve_exit()` — centralized OHLC exit resolver.
  - Stop branch `:167–173`, TP branch `:175–181`. **Priority SL → TP**, intrabar,
    first-hit returns. This ordering *is* the OCO, and the SL-first check *is* the
    pessimistic same-bar tie-break (if both SL and TP are touched in one bar, SL wins).
  - Wired in-loop at `:466–479` — `position_state` built from `stop_price_active`
    (mutable) + `tp_price` (fixed at entry).

### Entry-side bracket construction (ATR stop / TP)
- `execution_loop.py:269–285` — parse `STRATEGY_SIGNATURE.execution_rules.stop_loss`
  / `take_profit` `atr_multiplier`; SL default `ENGINE_ATR_MULTIPLIER = 2.0`
  (`:82`); TP `None` unless configured/enabled.
- `execution_loop.py:360–388` → `evaluate_bar.py::build_position_from_pending` —
  sets `stop_price`, `tp_price`, `risk_distance` at fill.
- Strategy may instead supply absolute `stop_price` / `tp_price` at entry
  (`contract.json` `entry_interface.optional_keys`); engine falls back to 2·ATR
  stop when absent.

### Partial close (scale-out)
- `execution_loop.py:481–521`.
  - Guards `:485–489`: `bars_held ≥ _PARTIAL_MIN_BARS_HELD (1)` AND
    `unrealized_r ≥ _PARTIAL_MIN_UNREALIZED_R (1.0001)`.
  - Hook call `:491` `strategy.check_partial_exit(ctx)`.
  - Fraction clamp `[0.01, 0.99]` — `_PARTIAL_FRACTION_MIN/MAX` `:90–91`.
  - **Once-per-trade lock:** `partial_taken = True` at `:521` — no further partial
    fires for the life of the trade.

### Dynamic stop / break-even / trailing (all one hook)
- `execution_loop.py:523–543` `check_stop_mutation(ctx)`.
  - **Monotone gate** `:534–537`: longs may only raise SL, shorts may only lower
    SL; non-monotone updates silently rejected + counted in `stop_mutation_rejected`.
  - New stop stored in `stop_price_active` `:539`; because step-1 (`resolve_exit`)
    already ran this bar, the new level **takes effect from the next bar**.
  - `initial_stop_price` is FROZEN — the risk-distance denominator for
    `unrealized_r` never mutates, even after a stop move or partial.

### BE / trailing support fields (ctx)
- `execution_loop.py:186–200` `_compute_unrealized_r` (close-based).
- `execution_loop.py:203–220` `_compute_unrealized_r_intrabar` (bar_high/low based).
- `contract.json` `ctx_additions`: `entry_price`, `unrealized_r`,
  `unrealized_r_intrabar` — documented as exposed *"so check_stop_mutation can
  construct a BE stop price without the strategy needing to cache it."* Use
  `unrealized_r_intrabar` for BE/trail triggers so they align with the intrabar
  SL/TP resolver.

### Authoritative per-bar ordering
- `execution_loop.py:458–464` + `contract.json` `per_bar_ordering`:
  1. SL/TP resolution (`resolve_exit`) — intrabar, highest priority
  2. Partial exit — bar close, once per trade
  3. Stop mutation — applies from next bar
  4. `check_exit` (time/signal) — `:545–578`, bool, lowest priority

---

## Directive-classification decision rule

**Stays `rule_build_required: true`** (implement as a recycle rule / `strategy.py`
hook — no engine work): partial close, break-even, ATR trailing, monotone dynamic
stops, a single-SL + single-TP bracket, OCO, and single-scale-out-plus-trail.

**Becomes `engine enhancement required`** (needs a new versioned engine) when the
hypothesis's exit logic requires any of:
1. **Laddered / multiple TP targets**, or **multiple partials** (>1 scale-out per
   trade) — blocked by the `partial_taken` lock (`:521`) + the single `tp_price` slot.
2. **Non-monotone stop moves** (widening a stop, volatility-expansion stops) —
   rejected by the monotone gate (`:534–537`).
3. **Intrabar-reactive stop changes** — mutations only apply from the next bar.
4. **R-multiples re-based after a partial** — the risk denominator is frozen at the
   initial stop.

**One-line triage test:** if the exit is *one tightening stop + one TP + at most one
scale-out*, it is a rule build. If it needs *laddered targets, multiple partials,
stop-widening, or intrabar stop reaction*, flag `engine enhancement required`
before testing — otherwise the fail-closed mechanisms silently mis-model the exit.

---

## Provenance

- Verified against source 2026-07-02: `execution_loop.py`, `evaluate_bar.py`,
  `contract.json` in `engine_dev/universal_research_engine/v1_5_11/`.
- Engine status: FROZEN (freeze date 2026-06-24, Patch A core).
- This is a static capability audit (Invariant #31: advisory reference, not a
  pipeline-authoritative conclusion). Any exit-model behavior claim that will drive
  a promote/retire decision must still be reproduced through the pipeline.
