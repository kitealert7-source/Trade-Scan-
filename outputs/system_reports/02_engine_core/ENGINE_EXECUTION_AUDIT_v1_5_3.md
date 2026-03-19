# ENGINE EXECUTION AUDIT — v1.5.3
**File:** `engine_dev/universal_research_engine/v1_5_3/execution_loop.py`
**FilterStack:** `engines/filter_stack.py`
**Audit date:** 2026-03-17 | Up-to-date with Engine v1.5.3 Freeze.

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
**Verdict: PASS (Signature aligned)**

**Implementation** (`execution_loop.py` line 227):
```python
entry_price = row['close']
```

The engine enters at the **signal bar's close** (bar N close). Previously, legacy strategies declared `"execution_timing": "next_bar_open"`. In **v1.5.3**, the `execution_timing` metadata field was completely removed from the canonical capability map to eliminate this discrepancy. The signature now accurately reflects actual engine behavior.

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
**Verdict: PASS (Fields successfully added)**

Trade dict built at the end of the execution block. Fields present:

| Field | Present |
|---|---|
| `entry_index`, `exit_index` | YES |
| `entry_price`, `exit_price` | YES |
| `direction`, `bars_held` | YES |
| `entry_timestamp`, `exit_timestamp` | YES |
| `trade_high`, `trade_low` | YES |
| `volatility_regime`, `trend_score`, `trend_regime`, `trend_label` | YES |
| `atr_entry`, `initial_stop_price`, `risk_distance` | YES |
| **`exit_source`** (STOP / TP / TIME_EXIT / SIGNAL_EXIT) | **YES** |
| **`stop_source`** (STRATEGY / ENGINE_FALLBACK) | **YES** |

In v1.5.3, these metadata fields have been successfully exposed in `results_tradelevel.csv`, enabling deterministic PnL attribution post-execution.

---

## Summary Table

| # | Item | Verdict | File:Line |
|---|---|---|---|
| 1 | SL OHLC rule | PARTIAL PASS | `execution_loop.py` |
| 2 | TP OHLC rule | PASS | `execution_loop.py` |
| 3 | SL wins ambiguous bar | PASS | `if not exit_triggered` |
| 4 | `check_exit()` runs last, fills at close | PASS | `execution_loop.py` |
| 5 | Entry timing | **PASS** | `execution_timing` removed from signature; engine fills at close. |
| 6 | Session re-entry guard | **FAIL** | `state_machine`/`trade_management` keys silently skipped |
| 7 | Stop price origin | PASS | `execution_loop.py`; fallback = ATR × 2.0 |
| 8 | Gap-through stop fill | **FAIL** | no inner-bound guard; fills at stop_price not gap-open |
| 9 | Same-bar entry/exit | PASS | Structurally impossible — `if/else` mutex |
| 10 | Exit source / stop source metadata | **PASS** | Fields accurately captured in trade dict. |

**6 PASS · 1 PARTIAL PASS · 2 FAIL**

---

## Known Operational Constraints (Engine v1.5.3)

| Priority | Item | Issue | Status/Recommendation |
|---|---|---|---|
| MEDIUM | 6 | Session state machine (`no_reentry_after_stop`, `max_trades_per_session`) is unenforced. | To be addressed in Engine v2.0 refactor. Currently managed by cautious strategy design. |
| LOW | 8 | Gap-through stop fills at `stop_price` (optimistic). On 15M XAUUSD event candles this materially overstates fill quality. | Acceptable variance for v1.5.x constraints. Documented risk point. |
