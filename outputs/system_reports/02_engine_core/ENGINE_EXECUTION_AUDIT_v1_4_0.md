# ENGINE EXECUTION AUDIT — v1.4.0
**File:** `engine_dev/universal_research_engine/v1_4_0/execution_loop.py`
**FilterStack:** `engines/filter_stack.py`
**Audit date:** 2026-03-10 | Read-only, no modifications made.

---

## Section 1 — Execution Logic (Items 1–4)

---

### Item 1 — Stop Execution (OHLC Rule)
**Verdict: PARTIAL PASS**

**Implementation** (`execution_loop.py` lines 316–323):
```python
if direction == 1 and bar_low <= stop_price:
    exit_triggered = True
    exit_price = stop_price
elif direction == -1 and bar_high >= stop_price:
    exit_triggered = True
    exit_price = stop_price
```

| Check | Result |
|---|---|
| LONG triggers when bar_low ≤ stop_price | PASS |
| SHORT triggers when bar_high ≥ stop_price | PASS |
| Exit fills at stop_price, not bar_close | PASS |
| SL check runs before any strategy exit | PASS |
| Upper/lower bound enforced (stop inside bar range) | FAIL — see Item 8 |

The condition `bar_low <= stop_price` has **no upper bound** (`stop_price <= bar_high`). If the bar gaps entirely below the stop (LONG) or above the stop (SHORT), the stop still fires and fills at `stop_price` rather than at the gap-open. This is an optimistic fill — see Item 8 for the gap model.

---

### Item 2 — TP Execution (OHLC Rule)
**Verdict: PASS**

**Implementation** (`execution_loop.py` lines 325–332):
```python
if not exit_triggered and tp_price is not None:
    if direction == 1 and bar_high >= tp_price:
        exit_triggered = True
        exit_price = tp_price
    elif direction == -1 and bar_low <= tp_price:
        exit_triggered = True
        exit_price = tp_price
```

| Check | Result |
|---|---|
| LONG triggers when bar_high ≥ tp_price | PASS |
| SHORT triggers when bar_low ≤ tp_price | PASS |
| Only executes if SL was not already triggered | PASS (`if not exit_triggered`) |
| Evaluated before `check_exit()` | PASS (line 325 precedes line 335) |
| Fill at tp_price, not bar_close | PASS |

Same gap caveat as Item 1 applies: no inner-bound guard, so a gap-through TP fills at `tp_price` (pessimistic for TP — favours the strategy).

---

### Item 3 — Ambiguous SL + TP Bar
**Verdict: PASS**

The priority chain at lines 316–337 is sequential and exclusive:

```
1. SL check (lines 316–323)
2. TP check guarded by `if not exit_triggered` (line 326)
3. check_exit() guarded by `if not exit_triggered` (line 335)
```

If SL fires (`exit_triggered = True`), the `if not exit_triggered` guard on the TP block prevents TP from executing. **SL wins unconditionally on any same-bar conflict.**

---

### Item 4 — Strategy Exit Logic
**Verdict: PASS**

**Implementation** (`execution_loop.py` lines 334–337):
```python
if not exit_triggered and strategy.check_exit(ctx):
    exit_triggered = True
    exit_price = row['close']
```

| Check | Result |
|---|---|
| `check_exit()` called only after SL and TP checks | PASS |
| Strategy exits fill at `row['close']` | PASS |

---

## Section 2 — Entry Model (Item 5)

---

### Item 5 — Entry Timing
**Verdict: FAIL (mismatch between signature and implementation)**

**Implementation** (`execution_loop.py` line 227):
```python
entry_price = row['close']
```

The engine enters at the **signal bar's close** (bar N close). The strategy SIGNATURE declares:
```python
"order_placement": {"execution_timing": "next_bar_open", "type": "market"}
```

This field is written into the signature and logged, but **the engine never reads it**. There is no code path in `execution_loop.py` or `filter_stack.py` that consumes `execution_timing`. The actual implemented rule is always **bar N close fill**, regardless of signature intent.

**Impact:** For strategies that expect next-bar-open execution, the modelled entry price may be slightly better or worse than live (since close ≠ next open). For the Family 08 breakout strategies, entries are at the close-confirm bar's close, which is directionally correct but the signature is misleading.

---

## Section 3 — Session Control (Item 6)

---

### Item 6 — Session Re-Entry Guard
**Verdict: FAIL**

The STRATEGY_SIGNATURE declares three session-control rules:
```python
"state_machine": {
    "no_reentry_after_stop": True,
    "session_reset": "new_day"
},
"trade_management": {
    "max_trades_per_session": 1,
    "reentry": {"allowed": False}
}
```

**FilterStack** (`filter_stack.py` lines 42–82): iterates over signature keys and applies only those where `cfg.get("enabled", False)` is `True`. The `state_machine` and `trade_management` blocks have no `"enabled"` key → **they are silently skipped every bar**.

**Engine loop** (`execution_loop.py` line 190): the only guard is:
```python
in_pos = False  # boolean flag
```
Entry is attempted whenever `not in_pos`. Once a position closes (whether via stop, TP, or time exit), `in_pos` resets to `False` on the same bar. On the **next bar**, `check_entry()` is called again with no memory of whether a stop triggered earlier in the session.

**Actual behaviour:**
- `max_trades_per_session: 1` → NOT enforced
- `no_reentry_after_stop: True` → NOT enforced
- `session_reset: new_day` → NOT enforced (no day-boundary state reset exists)

The engine will allow multiple trades per day if the strategy generates multiple entry signals after a stop-out. Whether this occurs in practice depends on whether the indicator layer produces a second signal the same day.

---

## Section 4 — Stop Handling (Items 7–8)

---

### Item 7 — Stop Price Origin
**Verdict: PASS (mechanism correctly described)**

**Implementation** (`execution_loop.py` lines 250–292):

```
Priority 1: entry_signal.get("stop_price")              ← strategy-provided
Priority 2: entry_price ± (atr * ENGINE_ATR_MULTIPLIER) ← engine fallback
```

| Variable | Value | Location |
|---|---|---|
| `ENGINE_ATR_MULTIPLIER` | `2.0` | Line 15 (module constant) |
| ATR source | `ctx.require('atr')` | Line 256 — raises if missing |
| LONG fallback | `entry_price - (atr × 2.0)` | Line 264 |
| SHORT fallback | `entry_price + (atr × 2.0)` | Line 266 |

Hard invariants enforced (lines 270–282): LONG stop ≥ entry → `ValueError`; SHORT stop ≤ entry → `ValueError`; risk_distance ≤ 0 → `ValueError`.

**For all Family 08 strategies:** `check_entry()` returns `{"signal": 1}` or `{"signal": -1}` with no `stop_price` key → **always falls back to ATR × 2.0**. The `stop_loss: fixed_points: 50` declared in the signature is metadata only — it is never read by the engine.

---

### Item 8 — Gap Through Stop
**Verdict: FAIL (optimistic fill model)**

When the price gaps entirely through the stop level (entire bar on the wrong side), the engine still fills at `stop_price`:

**LONG gap-down example:**
- stop = 2,735; bar open/low/high/close = 2,720 / 2,715 / 2,725 / 2,722
- Condition: `bar_low (2,715) <= stop_price (2,735)` → True
- Engine fill: **2,735** (stop_price)
- Realistic fill: **≈2,720** (gap-open)
- Difference: **+$15 per unit** — engine overstates fill quality

The condition has no `stop_price <= bar_high` upper bound for LONG, so the fill is always at `stop_price` regardless of whether the bar ever traded there. On 15M XAUUSD bars this occurs on news/event candles (e.g., US Election Day, NFP).

The same logic applies symmetrically to SHORT (no `stop_price >= bar_low` lower bound).

---

## Section 5 — Trade State & Metadata (Items 9–10)

---

### Item 9 — Same-Bar Entry/Exit
**Verdict: PASS (structurally impossible)**

The entry and exit blocks are in mutually exclusive branches:

```python
if not in_pos:   # entry block — sets in_pos = True
    ...
else:            # exit block — only reached when in_pos = True
    ...
```

Entry sets `in_pos = True` at line 225. The exit block (`else`) is only reached when `in_pos` is already `True` from a prior bar. **Same-bar entry/exit cannot occur.** Earliest possible exit is bar N+1 after entry on bar N.

---

### Item 10 — Trade Diagnostics Metadata
**Verdict: FAIL (exit source and stop source not logged)**

Trade dict built at lines 341–361. Fields present:

| Field | Present |
|---|---|
| `entry_index`, `exit_index` | YES |
| `entry_price`, `exit_price` | YES |
| `direction`, `bars_held` | YES |
| `entry_timestamp`, `exit_timestamp` | YES |
| `trade_high`, `trade_low` | YES |
| `volatility_regime`, `trend_score`, `trend_regime`, `trend_label` | YES |
| `atr_entry`, `initial_stop_price`, `risk_distance` | YES |
| **`exit_source`** (STOP / TP / TIME_EXIT / SIGNAL_EXIT) | **MISSING** |
| **`stop_source`** (STRATEGY / ENGINE_FALLBACK) | **MISSING** |

Without `exit_source`, post-hoc analysis cannot distinguish between stop-outs, TP fills, and time exits from the raw trade log. Without `stop_source`, it is impossible to audit how many stops were strategy-defined vs ATR fallback in a given run.

---

## Summary Table

| # | Item | Verdict | File:Line |
|---|---|---|---|
| 1 | SL OHLC rule | PARTIAL PASS | `execution_loop.py:316–323` |
| 2 | TP OHLC rule | PASS | `execution_loop.py:325–332` |
| 3 | SL wins ambiguous bar | PASS | `execution_loop.py:326` (`if not exit_triggered`) |
| 4 | `check_exit()` runs last, fills at close | PASS | `execution_loop.py:334–337` |
| 5 | Entry timing | **FAIL** | Actual: bar-N close (`line 227`); signature claims `next_bar_open` — field unread by engine |
| 6 | Session re-entry guard | **FAIL** | `filter_stack.py:42–82` — `state_machine`/`trade_management` keys silently skipped |
| 7 | Stop price origin | PASS | `execution_loop.py:251–268`; fallback = ATR × 2.0 (`line 15`) |
| 8 | Gap-through stop fill | **FAIL** | `execution_loop.py:318,321` — no inner-bound guard; fills at stop_price not gap-open |
| 9 | Same-bar entry/exit | PASS | Structurally impossible — `if/else` mutex (`lines 213, 299`) |
| 10 | Exit source / stop source metadata | **FAIL** | Trade dict `lines 341–361` — neither field present |

**4 PASS · 1 PARTIAL PASS · 4 FAIL**

---

## Critical Gaps Before Freezing Execution Layer

| Priority | Item | Issue | Recommended Fix |
|---|---|---|---|
| HIGH | 6 | Session state machine (`no_reentry_after_stop`, `max_trades_per_session`) is entirely unenforced. Engine can re-enter same day after stop. | Add day-keyed session state to the loop; check date boundary before calling `check_entry()`. |
| HIGH | 5 | `execution_timing: next_bar_open` declared in signature but engine always fills at bar-N close. | Either implement one-bar delay in the loop (shift entry to `df.iloc[i+1]['open']`), or remove the field from the signature template. |
| MEDIUM | 8 | Gap-through stop fills at `stop_price` (optimistic). On 15M XAUUSD event candles this materially overstates fill quality. | Add `bar_low <= stop_price <= bar_high` range guard; fill at `bar_open` when stop is outside bar range. |
| LOW | 10 | No `exit_source` or `stop_source` in trade records. Blocks post-hoc PnL attribution. | Add `exit_source` and `stop_source` fields to the trade dict at exit time. |
