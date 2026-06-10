# ZCRS exit-fill timing: same-bar lookahead — decision record (2026-06-10)

**Question:** ZCRS exited at the zero-cross bar's own close. Is that lookahead,
how much did it inflate the backtest, and should the realistic M+1-open exit
become the standard?

**Decision (this record): ship the realistic exit as an opt-in capability
(default-off) + a regression fixture; LEAVE THE LIVE DEMO ALONE; DEFER the
"make next_open the canonical backtest default" call.** This is candidate
**ZCRS v3** — investigated and quantified, not yet promoted.

## Findings (workflow-verified; adversarially upheld on all checks; high confidence)
- **Same-bar exit lookahead CONFIRMED.** The zcross column is `sign(z[t]) !=
  sign(z[t-1])` computed from bar t's close (no `.shift()`); `_liquidate` fills at
  `bar_closes[M]` (bar M's close) with `exit_index = M`. Detect + fill on the same
  bar = lookahead. **Asymmetric** with the entry, which defers to next-bar-open.
- **The LIVE demo is already realistic (M+1), NOT lookahead.** Verified against the
  broker statement: real closes land **~17.3 min (1.15 bars) after the zero-cross
  bar** — the producer-computes-after-close → shim-market-order chain supplies the
  one-bar lag the backtest omits. **So the lookahead is BACKTEST-ONLY.**
- **Inflation is modest in aggregate, material on high-cycle baskets.** next_open
  vs bar_close (exit isolated, 20 deployable pairs): sum net **122.6 → 119.0
  (+3.0% relative)**, mean **−0.18pp/pair**; 13/20 degrade, 7/20 improve. The
  improvements are legitimate path-dependence (the one-bar defer reshuffles
  downstream re-entries → different cycle sets), **not** reverse lookahead
  (independently re-derived). Material on **CADJPYUSDCHF: −3.6pp net, Ret/DD
  1.57 → 1.08 (−31%)** — the same-bar edge compounds over its ~200 cycles. (It is
  also the biggest N+1-entry winner; the two timing corrections roughly offset.)
- **The v2 (N+1 entry) decision is unaffected** — the exit lookahead sat
  identically in both N+1 and N+2 sweep arms, so it cancels in that comparison.

## Implementation (opt-in, parity-preserving, rule-level — frozen engine untouched)
- `exit_fill_timing` param on `PineRatioZRevRuleZCross`: **"bar_close" (default =
  current, byte-identical)** | "next_open" (defer one bar, fill at M+1's OPEN via
  `_liquidate_at_prices`, tracked by `_pending_exit`).
- Edge cases proven: EOF zero-cross force-closes at the terminal bar; cointegration-
  break clears the pending exit and takes precedence (no double-fire); time-stop
  coinciding with a pending exit fires exactly once.
- **Parity:** default path byte-identical (recycle_events + per_bar_records
  identical; 16/16 parity suite). **next_open:** 77/77 EQUILIBRIUM exits fill
  exactly one bar later at the OPEN (≠ M+1 close, ≠ M close), no same-bar fill —
  independently adversarially re-derived. Shipped **default-off** + a committed
  regression fixture (`tests/test_pine_zrev_exit_fill_timing.py`).

## Why v3 is NOT a live change (mirror image of the entry fix)
The entry artifact was *live* (the producer/shim genuinely filled late → N+1 fixed
it). The exit lookahead is **backtest-only** — the live demo already exits at M+1.
Pushing `next_open` onto the **live producer** would move the target FLAT to M+1
and the broker close to **M+2 — strictly worse**. So the live producer correctly
stays `bar_close` (target FLAT at M → shim closes at M+1, the earliest realistic
exit). **No demo restart; v2 continues unchanged.**

## Deferred
**Making `next_open` the canonical backtest default** is a separate methodology
call, deferred. Adopting it would lower future backtest/promotion numbers by the
~3% aggregate (locally larger) honest haircut and would re-baseline existing
promotions (all done on bar_close). The live demo is the true measure regardless;
the demo-outcome ledger will independently surface the gap as N+1-era cycles
accumulate. Revisit when re-baselining research is warranted.
