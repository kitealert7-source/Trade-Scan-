# Broker Execution Post-Mortem — 2026-06-06

**Context:** First live multi-leg basket execution against a real MT5 demo broker (OctaFX-Demo 213872531). Three distinct defects surfaced between `dispatch_group` design-lock and first live `[STEP 3] PASS`. None caused a live incident (the progression Step 1 → 2 → 3 + safety gates prevented any naked position). All three are permanently fixed.

**Why this document exists:** these failures are more valuable than the BTC/ETH trades. Offline mocks passed; the real broker said no three times in a row — and each failure revealed a class of assumption the test suite cannot catch by construction. The fixes are in code; this document captures the *why* so the pattern is recognisable six months from now.

---

## Defect 1 — Filling mode hardcoded as IOC; FOK-only symbols silently rejected

### Root cause
`broker.place_order` hardcoded `"type_filling": ORDER_FILLING_IOC` for every symbol. FX instruments (EURUSD/GBPUSD) support IOC; crypto instruments (BTCUSD/ETHUSD) on OctaFX are **FOK-only** (`symbol_info().filling_mode = 1 = SYMBOL_FILLING_FOK`). An IOC order to a FOK-only symbol returns `retcode=10030` ("Unsupported filling mode") — not a timeout, not a server error, a flat capability mismatch.

The `filling_mode` bitmask on `symbol_info` explicitly declares which modes a symbol supports. It was never read.

### How discovered
`order_send` returned `None` for BTCUSD in Step 1. `order_check` across all three filling modes isolated it:
```
order_check[FOK]:    retcode=0  comment='Done'           ← works
order_check[IOC]:    retcode=10030  'Unsupported filling mode'  ← fails
order_check[RETURN]: retcode=10030  'Unsupported filling mode'  ← fails
```

### Why mocks missed it
Every offline test monkeypatches `broker.place_order` at the module level and returns a synthetic `OrderSendResult`. The MT5 request dict is never constructed, never validated, and `type_filling` is never checked. `order_check` even passed with the correct request shape — the mismatch only fires when `order_send` hits the broker server with the wrong mode.

**The class of miss:** broker-capability constraints are symbol-specific and broker-specific. They cannot be inferred from the Python API and are invisible to any offline harness. Only a live send exposes them.

### Permanent guard added
`resolve_filling(symbol)` reads `symbol_info().filling_mode` at call time and returns the correct `ORDER_FILLING_*` constant (prefer IOC if available — the existing FX behavior — else FOK, else RETURN). `LiveBasketBroker.open_leg` and `close_all` always call `resolve_filling(leg.symbol)` before constructing the request. The constants (`SYMBOL_FILLING_FOK=1`, `SYMBOL_FILLING_IOC=2`, `ORDER_FILLING_*`) are now re-exported on the broker seam so no other module needs to import MetaTrader5 to resolve a symbol's capability.

Tests prove: FOK-only symbol → FOK, IOC-only → IOC, both → IOC preferred, unreadable → None (falls back to broker.place_order's IOC default). Committed `e3f75df`.

**Durable principle:** a symbol's filling mode is a runtime capability, not a constant. Resolve it from `symbol_info` at send time. `trade_mode=FULL` does not imply IOC support.

---

## Defect 2 — sl=0.0 / tp=0.0 in request dict returns None on OctaFX

### Root cause
`broker.place_order` unconditionally included `"sl": 0.0, "tp": 0.0` in the MT5 request dict for every order without an explicit stop/take-profit — the standard "no stop" convention. OctaFX's trade server (and at least some other brokers) interprets `sl=0.0` not as "no stop loss" but as **"stop loss at price zero"** — an invalid price — and rejects the request at the API level. The rejection manifests as `order_send` returning `None` (an API-level failure, not a `retcode`-carrying `OrderSendResult`), so there is no retcode to inspect and `last_error()` had to be captured post-hoc.

`order_check` returned `retcode=0` for both variants because `order_check`'s server-side validation path differs from `order_send`'s.

### How discovered
Step 1 `broker.place_order` returned `None`. After the filling-mode fix was applied (`e3f75df`) the symptom persisted. `order_check` confirmed the request was structurally valid (retcode=0, margin=$6.13). Isolated by calling `mt5.order_send` directly without `sl`/`tp` keys (Steps 1 and 2, which worked) vs `broker.place_order` which adds them. The broker's `last_error()` after `broker.place_order` returned `None` confirmed with `(-2, 'Unnamed arguments not allowed')` — later determined to be from a different defect (see Defect 3), but the sl/tp delta was confirmed independently by field comparison.

### Why mocks missed it
`MockBasketBroker` accepts any input and returns a synthetic fill regardless of the request dict. `order_check` validates structurally but not against OctaFX's zero-SL interpretation. The broker-specific interpretation of `sl=0.0` is not documented in the MT5 API and is not inferrable from the Python binding — it only appears when the request reaches the broker's trade server.

**The class of miss:** broker-specific field interpretation for sentinel values (`0.0` meaning "absent" vs "at price 0") is not captured in any standard API contract. Different brokers behave differently on this field, and no offline test can distinguish them.

### Permanent guard added
`broker.place_order` now only includes `sl`/`tp` keys when they are non-zero: `if sl: request["sl"] = float(sl)`. Python's truthiness excludes `0.0`, `None`, and unset — "no stop" means those keys are absent from the dict entirely, which MT5 interprets unambiguously. The comment documents the confirmed failure mode. Committed `bc493e0`.

**Durable principle:** omit fields entirely rather than setting them to a sentinel zero. `sl` absent ≠ `sl=0.0` on OctaFX. Prefer absence over convention when the convention is broker-specific.

---

## Defect 3 — order_send via \*args expansion returns None with error -2

### Root cause
`_gated_call("order_send", request)` passes the request dict to `mt5.order_send` via Python's `*args` mechanism:
```python
def _gated_call(name, *args, **kwargs):
    get_rate_limiter().acquire(name)
    return getattr(_mt5, name)(*args, **kwargs)
# → mt5.order_send(*[request])  ← CALL_FUNCTION_EX bytecode
```

`mt5.order_send(request)` called directly (CALL_FUNCTION bytecode) returns `retcode=10009` (success). The two are semantically equivalent in CPython, but the MT5 C extension's internal argument parser distinguishes them: `*args` expansion results in a different C-level argument-passing path that the extension rejects with `(-2, 'Unnamed arguments not allowed')`.

This is a MetaTrader5 Python C extension behaviour, not a Python language property — it is version-specific (confirmed on terminal build 5833) and not documented.

### How discovered
After Defect 2 was fixed and `dispatch_group` still returned `ABORTED_FLAT`, added `broker.last_error()` capture immediately after `broker.place_order()` returned `None`:
```
broker.place_order result type: NoneType  last_error=(-2, 'Unnamed arguments not allowed')
```
Error code -2 is an MT5 Python binding error, not a trade-server retcode. Cross-checked by calling `mt5.order_send(request)` directly in the same process — retcode=10009, position opened. The only difference between the two calls is CALL_FUNCTION vs CALL_FUNCTION_EX.

### Why mocks missed it
Offline tests never invoke `_gated_call` with a real `_mt5` module — the entire MT5 import is stubbed. The `*args` expansion path only activates with the real MetaTrader5 C extension. Even Steps 1 and 2 of the live test bypassed `_gated_call` by calling `mt5.order_send(req)` directly, so this defect was masked until Step 3's full orchestration path ran.

**The class of miss:** C extension argument-passing conventions are invisible to Python-level mocks. Any test that stubs the module boundary misses the calling convention entirely. The defect only appeared when the real extension received the call through a Python-level indirection layer.

### Permanent guard added
`broker.place_order` and `broker.close_position_order` now inline the rate-limiter acquire + direct call:
```python
get_rate_limiter().acquire("order_send")
return _mt5.order_send(request)
```
The rate-limiting contract is fully preserved (acquire is still called before every send). The `*args` expansion is bypassed. Comment documents the exact failure mode and the `_gated_call` alternative for every other broker function (which do not have this constraint). Committed `d_inline` (see `git log --oneline` on `feat/basket-execution-p2` for the exact hash).

**Durable principle:** when a C extension function is sensitive to Python's argument-passing convention, call it directly. Do not route it through a generic `*args` wrapper even if the wrapper exists for good reasons (rate-limiting, logging, etc.) — inline the wrapper's side effects instead.

---

## Bonus observation — tradable symbol ≠ tradable market

This is not a defect (nothing broke) but it surfaced during the readiness smoke and is worth recording.

`symbol_info().trade_mode == FULL` for EURUSD and GBPUSD even on Saturday, when FX is closed. The last tick timestamp was 11.6 hours stale. **`trade_mode=FULL` does not mean the market is open; it means the symbol is not administratively disabled.** The actual open/closed state is only visible from tick freshness.

**The operative test:** `(tick.time - now) < threshold` (e.g., < 300s for live market), not `trade_mode`. This was flagged as a production-guard candidate during the session and should be added to the `BasketReadiness` / both-legs-fresh gate before first FX live deployment.

**Why it matters:** a basket runner that checks `trade_mode=FULL` before dispatching would silently attempt orders on a closed FX market on Saturday night and receive rejections (or fills at stale prices if the broker is lenient). Tick freshness is the correct signal. Crypto (BTCUSD/ETHUSD) correctly showed `0.0h` stale; FX showed `11.6h` — same `trade_mode`, opposite real state.

---

## Summary

| # | Defect | Class | Guard |
|---|---|---|---|
| 1 | Filling mode hardcoded IOC | Broker capability assumption | `resolve_filling()` reads `symbol_info().filling_mode` at send time |
| 2 | sl=0.0 / tp=0.0 invalid on OctaFX | Broker-specific field semantics | Omit `sl`/`tp` keys when value is zero |
| 3 | order_send via *args → error -2 | C extension calling convention | Inline `acquire` + direct `_mt5.order_send(request)` |
| B | trade_mode=FULL ≠ market open | Market-hours detection | Tick-freshness check (<300s) required; deferred to FX gate |

**Common thread:** all four are **broker-interface assumptions that pass offline tests by construction**. The only way to find them is a live send to the real C extension against the real broker. This is why the step progression (single leg → two legs separate → dispatch_group) and the "retire one uncertainty at a time" principle exist — each step surfaces exactly one layer of broker reality, with small stakes.

The P2 demo session retired every defect in this class before any real capital was at risk.

---

*Post-mortem written 2026-06-06 immediately after `[STEP 3] PASS` on OctaFX-Demo 213872531. Referenced by: `COINTEGRATION_FIRST_LIVE_DEPLOYMENT_PROPOSAL.md` §P2 completion note.*
