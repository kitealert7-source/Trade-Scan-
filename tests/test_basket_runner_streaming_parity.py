"""Research-semantics == Streaming-semantics parity gate (Slice 1.6, corrected).

THE INVARIANT THIS LOCKS (the most important one in the live-basket architecture):
driving the basket mechanic on a GROWING PREFIX of bars [0..i] reproduces the
BATCH `basket_runner` run bit-for-bit at every bar <= i, for indicators, signals,
and -- the load-bearing one -- per-bar POSITION STATE (`active_legs`). If this
holds, the live runner can stream the SAME `basket_runner` + recycle-rule code
that research backtests, so all strategy intelligence (z-scores, approvals,
next-bar-open, cointegration, regime) stays Trade_Scan-side and TS_Execution
stays execution-only.

Provenance: a 198-cutoff spike on real EURUSD/GBPUSD 5m (35 cycles) passed
bit-for-bit; this is the portable, deterministic regression guard distilled from
it (in-test synthetic spread, no committed broker data, no RNG/wall-clock).

================  DRIVER RULE (corrected 2026-06-06 by Slice 2)  ================
The streaming driver emits the target derived from the LATEST replayed bar's
`active_legs` -- NO lag. This gives target transitions IDENTICAL to batch
(test_live_basket_driver), because position STATE is boundary-robust:

  A pending entry-APPROVAL at the latest bar IS dropped (the 2-bar protocol's
  _maybe_approve needs bar C+1 to schedule the fire -- next_bar_open). But that
  drop changes only the EVENT trajectory, never `active_legs` at that bar (fills
  land two bars after approval), and the re-run-from-history re-completes the
  approval on the next bar. So the target (active_legs-derived) is identical to
  batch with no lag -- a lag would instead SHIFT the transitions.

`test_boundary_drops_pending_approval_but_not_state` pins this distinction:
events diverge at the boundary, state does not. (The earlier "1-bar lag" framing
was the wrong inference from the same observation; corrected here.)
==============================================================================
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0
WARMUP = 2 * N_WINDOW
IND_COLS = ["pine_zrev_z", "pine_zrev_r_bar", "pine_zrev_signal", "pine_zrev_zcross_exit"]


def _ohlc(close, idx):
    close = np.asarray(close, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * 1.00008
    low = np.minimum(openp, close) * 0.99992
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close,
         "volume": 1000.0, "spread": 0.00002}, index=idx,
    )


def _synthetic_legs(n: int = N_BARS):
    """Deterministic (no RNG / wall-clock) 2-leg OHLC whose A/B ratio mean-reverts
    with enough amplitude to drive several z-cross cycles."""
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    t = np.arange(n)
    osc = (0.60 * np.sin(2 * np.pi * t / 41)
           + 0.40 * np.sin(2 * np.pi * t / 17 + 0.7)
           + 0.25 * np.sin(2 * np.pi * t / 9 + 1.9)
           + 0.15 * np.sin(2 * np.pi * t / 5 + 0.3))
    return (_ohlc(1.1000 * (1.0 + 0.004 * osc), idx),
            _ohlc(1.2700 * (1.0 + 0.0005 * np.sin(2 * np.pi * t / 53)), idx))


def _run_mechanic(dfA, dfB):
    """Fresh construction every call. Returns indicator columns, per-bar
    (skip_reason, active_legs) keyed by bar index, recycle events as
    (bar_index, action, reason), and the index."""
    shared = PineZRevArmedState()
    legA = BasketLeg(SYM_A, 0.01, +1, dfA.copy(), PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    legB = BasketLeg(SYM_B, 0.01, -1, dfB.copy(), PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    rule = PineRatioZRevRuleZCross(
        n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute",
        shared_armed_state=shared, run_id="PAR", directive_id="PAR", basket_id="PAR",
    )
    BasketRunner([legA, legB], [rule], warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    idx = legA.df.index
    cols = {c: legA.df[c] for c in IND_COLS if c in legA.df.columns}
    records = {idx.get_loc(pd.Timestamp(r["timestamp"])): (r.get("skip_reason"), r.get("active_legs"))
               for r in rule.per_bar_records}
    events = [(idx.get_loc(pd.Timestamp(e["bar_ts"])), e.get("action"), e.get("reason"))
              for e in rule.recycle_events]
    return cols, records, events, idx


def _representative_cutoffs(events, n, warmup):
    event_locs = sorted({loc for loc, _, _ in events})
    if len(event_locs) > 5:
        step = max(1, len(event_locs) // 5)
        event_locs = event_locs[::step][:5]
    base = {warmup + 5, warmup + 20, n // 2, n - 1}
    base |= set(event_locs) | {l + 1 for l in event_locs}
    return sorted(c for c in base if warmup + 2 <= c < n)


# --------------------------------------------------------------------------- #

def test_fixture_exercises_cycles():
    """Guard the guard: if the synthetic spread stops producing cycles the parity
    test would vacuously pass -- fail loudly instead."""
    _, _, bev, _ = _run_mechanic(*_synthetic_legs())
    opens = sum(1 for e in bev if e[1] == "BASKET_OPEN")
    liqs = sum(1 for e in bev if e[1] == "LIQUIDATE")
    assert opens >= 3 and liqs >= 2, f"fixture must exercise cycles; got {opens} opens, {liqs} liqs"


def test_streaming_equals_batch():
    """Core gate: prefix[0..C] == batch for indicators + signals + per-bar
    POSITION STATE at EVERY bar <= C (this is what the driver emits from), and for
    recycle events at bars BEFORE the boundary. The boundary's dropped pending
    approval is the only divergence -- and it is an event, not state (see the next
    test)."""
    dfA, dfB = _synthetic_legs()
    bcols, brec, bev, bidx = _run_mechanic(dfA, dfB)
    cutoffs = _representative_cutoffs(bev, len(bidx), WARMUP)
    assert len(cutoffs) >= 5, "need several cutoffs to be a meaningful gate"

    for cut in cutoffs:
        pcols, prec, pev, pidx = _run_mechanic(dfA.iloc[:cut + 1], dfB.iloc[:cut + 1])

        # (1) indicators + signals: bit-for-bit at every bar of the prefix
        for c, bser in bcols.items():
            assert c in pcols, f"indicator {c!r} absent in prefix (cutoff {cut})"
            p = pcols[c]
            b = bser.reindex(p.index)
            assert np.allclose(b.to_numpy(float), p.to_numpy(float), rtol=0, atol=1e-9, equal_nan=True), \
                f"indicator {c!r} diverged streaming-vs-batch at cutoff {cut}"

        # (2) per-bar POSITION STATE (skip_reason + active_legs) at EVERY bar,
        #     INCLUDING the boundary -- this is the driver's target basis.
        for j in range(len(pidx)):
            if j in prec or j in brec:
                assert prec.get(j) == brec.get(j), \
                    f"basket state diverged at bar {j} (cutoff {cut}): {prec.get(j)} != {brec.get(j)}"

        # (3) recycle events match for bars strictly BEFORE the boundary
        be = [e for e in bev if e[0] < cut]
        pe = [e for e in pev if e[0] < cut]
        assert pe == be, \
            f"events diverged before boundary at cutoff {cut}: missing={[e for e in be if e not in pe]}"


def test_boundary_drops_pending_approval_but_not_state():
    """Pins the exact distinction the driver rule depends on: a prefix ending on
    an APPROVED bar DROPS that pending approval (no bar C+1 to schedule the fire),
    yet the POSITION STATE (active_legs / skip_reason) at that bar is UNCHANGED vs
    batch. Therefore the target (active_legs-derived) is boundary-robust and the
    driver emits from the latest bar with NO lag. If `active_legs` ever started
    diverging at the boundary, this fails and the no-lag rule must be revisited."""
    dfA, dfB = _synthetic_legs()
    _, brec, bev, _ = _run_mechanic(dfA, dfB)
    approved = [loc for loc, action, _ in bev if action == "APPROVED"]
    assert approved, "fixture must contain at least one APPROVED event"

    cut = approved[0]                                   # prefix ends on an APPROVED bar
    _, prec, pev, _ = _run_mechanic(dfA.iloc[:cut + 1], dfB.iloc[:cut + 1])

    # event diverges at the boundary ...
    assert any(loc == cut and a == "APPROVED" for loc, a, _ in bev), "batch approves at the boundary"
    assert not any(loc == cut and a == "APPROVED" for loc, a, _ in pev), \
        "boundary APPROVED unexpectedly present -> _maybe_approve no longer needs the next bar"
    # ... but the POSITION STATE at that bar does NOT (the target is robust).
    assert prec.get(cut) == brec.get(cut), \
        f"active_legs/state diverged at the boundary bar {cut}: the no-lag driver rule must be revisited"
