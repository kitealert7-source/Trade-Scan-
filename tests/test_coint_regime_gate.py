"""Validation suite for the live cointegration-regime gate (D3, 2026-06-10).

The gate is the `coint_break_exit` opt-in on PineRatioZRevRule(ZCross): when on,
the rule reads a per-bar `coint_regime` column (the DAILY 1d/252 screener regime,
ffill-projected onto the 15m grid by basket_data_loader in research and by the
live producer's `_attach_coint_regime` in production) and

  * LIQUIDATEs any open basket to FLAT the moment the regime leaves
    'cointegrated' (exit on 'breaking' OR 'broken'), tagged LIQUIDATE_REGIME_BREAK;
  * LATCHES `_regime_broken` so it never re-enters the dead spread;
  * RESETS that latch (re-enables the unchanged z-cross entry) the bar the regime
    RETURNS to 'cointegrated' -- the only rule-logic change this suite guards.

The screener's DB regime is hysteresis-classified (5-day persistence: 'cointegrated'
needs p<0.05 now AND >=4/5 priors <0.05); these fixtures DO NOT exercise that
classifier -- they inject a CONTROLLED `coint_regime` sequence directly onto the
leg dfs and assert the rule's exit/latch/reset response to it.

Harness mirrors tests/test_pine_zrev_exit_fill_timing.py and
tests/test_basket_runner_streaming_parity.py: deterministic (no RNG / wall-clock)
2-leg OHLC driven through the REAL engine path (BasketRunner.run(fast_path=False)),
so entries fill next-bar-open exactly as in research/live.

The injected regime transitions are placed against the KNOWN baseline trajectory
of this fixture (mapped once, flag-off): the basket opens at locs 84..101,
110..119, 126..142, 146..165, ... The break span is dropped INSIDE the 84..101
open window; the re-cointegration boundary is placed in a FLAT gap before a
later signal-driven open, so the assertions are discriminating, not vacuous.

Cases:
  A. test_A_no_regime_change_identical    -- all 'cointegrated' + flag ON
                                             == flag OFF, byte-identical.
  B. test_B_break_exits_at_breaking_no_reentry
                                          -- coint->breaking->broken: liquidate
                                             at the FIRST 'breaking' bar, no reentry.
  C. test_C_reentry_only_after_recointegration
                                          -- coint->breaking->broken->coint: one
                                             break-liquidation, flat through broken,
                                             reenter only on/after re-cointegration.
  C2.test_C2_multibreak_fsm               -- TWO break-and-recovery cycles
                                             (coint->breaking->broken->coint->
                                             breaking->coint): the latch SETS and
                                             CLEARS twice. Proves a finite-state
                                             machine, not a one-shot reset -- the
                                             second break must re-set the latch
                                             (exit again) and the second recovery
                                             must clear it again (re-enter again).
  D. test_D_flag_off_byte_identical       -- flag OFF (and unset): byte-identical
                                             to the no-regime-column baseline; the
                                             gate is fully inert.
"""
from __future__ import annotations

import math

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

# Baseline trajectory landmarks (flag-off, mapped from this exact fixture):
#   first open span: locs 84..101  (entry approved 82, opens 84, eq-exit 102)
#   then opens at 110, 126, 146, 170, ...
# We drop the break span inside 84..101 and resume cointegration in a flat gap.
_FIRST_OPEN = 84          # first stable open bar of the fixture
_BREAK_AT = 90            # a 'breaking' bar WHILE the basket is open (84..101)
_BROKEN_FROM = 91         # 'broken' thereafter
_RECOINT_AT = 150         # regime returns to 'cointegrated' (flat gap; next open ~170)

# Multi-break FSM landmarks (test_C2). Same flag-off trajectory as above; the
# open/eq-exit cycles are 76-80, 84-102, 110-120, 126-143, 146-166, 170-181, ...
# Two break-and-recovery cycles are threaded through it:
#   BREAK #1   loc  90 : 'breaking' INSIDE the open 84..102 span -> regime-break exit
#   BROKEN     loc  91 : 'broken' through the dead span (suppresses the 110 open)
#   RECOINT #1 loc 122 : 'cointegrated' in the FLAT gap (120,126) -> re-enable; next open 126
#   BREAK #2   loc 150 : 'breaking' INSIDE the open 146..166 span -> SECOND regime-break exit
#   RECOINT #2 loc 160 : 'cointegrated' in the FLAT gap (150,170) -> re-enable; next open 170
_FSM_BREAK_1 = 90
_FSM_BROKEN_1 = 91
_FSM_RECOINT_1 = 122
_FSM_BREAK_2 = 150
_FSM_RECOINT_2 = 160


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
    """Deterministic 2-leg OHLC whose A/B ratio mean-reverts with enough
    amplitude to drive several z-cross cycles -- identical oscillator to the
    streaming-parity / exit-fill-timing harnesses."""
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    t = np.arange(n)
    osc = (0.60 * np.sin(2 * np.pi * t / 41)
           + 0.40 * np.sin(2 * np.pi * t / 17 + 0.7)
           + 0.25 * np.sin(2 * np.pi * t / 9 + 1.9)
           + 0.15 * np.sin(2 * np.pi * t / 5 + 0.3))
    return (_ohlc(1.1000 * (1.0 + 0.004 * osc), idx),
            _ohlc(1.2700 * (1.0 + 0.0005 * np.sin(2 * np.pi * t / 53)), idx))


def _regime_series(idx, *, transitions) -> pd.Series:
    """Build a per-bar regime Series over the bar index from a list of
    (start_loc, regime) transitions. The regime is held (ffill-style) from each
    transition's start_loc until the next. Bars before the first transition take
    the first transition's regime (the whole pre-window is 'cointegrated' in
    every fixture here)."""
    regimes = pd.Series("cointegrated", index=idx, dtype="object")
    for start_loc, label in transitions:
        regimes.iloc[start_loc:] = label
    return regimes


def _run(coint_break_exit, *, regime_transitions=None, attach_regime=True, n=N_BARS):
    """Fresh construction + full engine-path run. Returns (rule, legA, legB).

    `attach_regime=False` runs with NO `coint_regime` column at all (the baseline
    the flag-off parity test compares against). `coint_break_exit=None` leaves the
    flag UNSET (dataclass default False) -- distinct from the explicit bool."""
    dfA, dfB = _synthetic_legs(n)
    dfA, dfB = dfA.copy(), dfB.copy()
    if attach_regime:
        reg = _regime_series(dfA.index, transitions=regime_transitions or [])
        dfA["coint_regime"] = reg.to_numpy()
        dfB["coint_regime"] = reg.reindex(dfB.index).to_numpy()
    shared = PineZRevArmedState()
    legA = BasketLeg(SYM_A, 0.01, +1, dfA, PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    legB = BasketLeg(SYM_B, 0.01, -1, dfB, PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    kwargs = dict(
        n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute",
        shared_armed_state=shared, run_id="CRG", directive_id="CRG", basket_id="CRG",
    )
    if coint_break_exit is not None:
        kwargs["coint_break_exit"] = coint_break_exit
    rule = PineRatioZRevRuleZCross(**kwargs)
    BasketRunner([legA, legB], [rule],
                 warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    return rule, legA, legB


def _loc(leg, bar_ts) -> int:
    return leg.df.index.get_loc(bar_ts)


def _opens(rule, leg):
    return sorted(_loc(leg, e["bar_ts"]) for e in rule.recycle_events
                  if e.get("action") == "BASKET_OPEN")


def _break_liqs(rule, leg):
    return sorted(_loc(leg, e["bar_ts"]) for e in rule.recycle_events
                  if e.get("action") == "LIQUIDATE" and e.get("reason") == "REGIME_BREAK")


def _normalize_nan(records):
    """NaN-safe dict equality: per-bar records carry NaN floats (margin_level_pct
    when flat, gate_factor_value) that break raw == on otherwise-identical
    structures. Every non-NaN field is compared verbatim."""
    out = []
    for r in records:
        out.append({k: ("__NAN__" if isinstance(v, float) and math.isnan(v) else v)
                    for k, v in r.items()})
    return out


# --------------------------------------------------------------------------- #
# Guard the guard: confirm the baseline fixture opens at the landmarks the
# injected regime transitions rely on -- else B/C would assert vacuously.
# --------------------------------------------------------------------------- #

def test_fixture_landmarks_hold():
    rule, legA, _ = _run(False, attach_regime=False)
    opens = _opens(rule, legA)
    assert opens, "baseline fixture must open the basket"
    # An open spans the break window (the break must land WHILE open to exit).
    assert any(o <= _BREAK_AT for o in opens) and _FIRST_OPEN in opens, (
        f"break bar {_BREAK_AT} must fall inside an open span; opens={opens[:6]}"
    )
    # A signal-driven open exists AFTER the re-cointegration boundary (so the
    # reset has something to re-enable).
    assert any(o > _RECOINT_AT for o in opens), (
        f"need an open after re-cointegration loc {_RECOINT_AT}; opens={opens}"
    )


# --------------------------------------------------------------------------- #
# A. All 'cointegrated' + flag ON  ==  flag OFF, byte-identical.
# --------------------------------------------------------------------------- #

def test_A_no_regime_change_identical():
    """regime == 'cointegrated' on EVERY bar with coint_break_exit=True. No break
    ever fires and the latch never sets, so recycle_events + per_bar_records are
    BYTE-IDENTICAL to a coint_break_exit=False run on the same data. This pins
    that an all-cointegrated live feed reproduces the research corpus exactly."""
    r_on, _, _ = _run(True, regime_transitions=[])    # all 'cointegrated'
    r_off, _, _ = _run(False, regime_transitions=[])  # gate off, same column

    # Sanity: the fixture actually trades (else parity is vacuous).
    assert sum(1 for e in r_on.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    # No break ever fired and the latch never set.
    assert not any(e.get("reason") == "REGIME_BREAK" for e in r_on.recycle_events), (
        "an all-cointegrated feed must never fire a regime-break exit"
    )
    assert r_on._regime_broken is False, "latch must never set on an all-coint feed"

    assert r_on.recycle_events == r_off.recycle_events, (
        "recycle_events diverged: gate ON (all-coint) != gate OFF"
    )
    assert _normalize_nan(r_on.per_bar_records) == _normalize_nan(r_off.per_bar_records), (
        "per_bar_records diverged: gate ON (all-coint) != gate OFF"
    )


# --------------------------------------------------------------------------- #
# B. coint -> breaking -> broken: liquidate at first 'breaking' bar, no reentry.
# --------------------------------------------------------------------------- #

def test_B_break_exits_at_breaking_no_reentry():
    """regime: cointegrated -> 'breaking' (loc 90, basket open) -> 'broken' (91+,
    never returns). Assert the basket LIQUIDATEs (LIQUIDATE_REGIME_BREAK) at the
    FIRST breaking bar -- exit-on-breaking, not waiting for 'broken' -- and never
    re-enters while the regime stays breaking/broken."""
    transitions = [(_BREAK_AT, "breaking"), (_BROKEN_FROM, "broken")]
    rule, legA, legB = _run(True, regime_transitions=transitions)

    breaks = _break_liqs(rule, legA)
    assert breaks == [_BREAK_AT], (
        f"expected exactly one regime-break liquidation at the FIRST breaking bar "
        f"{_BREAK_AT}; got {breaks}"
    )
    # The exit is tagged LIQUIDATE_REGIME_BREAK in the per-bar record at that bar.
    rec_at_break = next(r for r in rule.per_bar_records
                        if _loc(legA, r["timestamp"]) == _BREAK_AT)
    assert rec_at_break["skip_reason"] == "LIQUIDATE_REGIME_BREAK"
    assert rec_at_break["active_legs"] == 0, "basket must be flat on the break bar"

    # No BASKET_OPEN at or after the break bar (latched; never re-enters).
    opens_after = [o for o in _opens(rule, legA) if o >= _BREAK_AT]
    assert opens_after == [], (
        f"no re-entry allowed while regime stays breaking/broken; got opens {opens_after}"
    )
    assert rule._regime_broken is True, "latch must remain set (regime never recovers)"


# --------------------------------------------------------------------------- #
# C. coint -> breaking -> broken -> coint-again: reenter only after re-coint.
# --------------------------------------------------------------------------- #

def test_C_reentry_only_after_recointegration():
    """regime: cointegrated -> 'breaking' (90) -> 'broken' (91) -> 'cointegrated'
    again (150). Assert: exactly ONE regime-break liquidation at 90, the basket
    stays FLAT through the entire broken span [90, 150), and it RE-ENTERS only
    on/after the re-cointegration boundary (loc 150) -- never during breaking/
    broken. This exercises the latch RESET (the sole rule-logic change)."""
    transitions = [(_BREAK_AT, "breaking"), (_BROKEN_FROM, "broken"),
                   (_RECOINT_AT, "cointegrated")]
    rule, legA, legB = _run(True, regime_transitions=transitions)

    breaks = _break_liqs(rule, legA)
    assert breaks == [_BREAK_AT], (
        f"expected exactly one regime-break liquidation at {_BREAK_AT}; got {breaks}"
    )

    opens = _opens(rule, legA)
    # Flat through the broken span: no open in [break, recoint).
    opens_in_dead = [o for o in opens if _BREAK_AT <= o < _RECOINT_AT]
    assert opens_in_dead == [], (
        f"basket must stay flat through breaking/broken [{_BREAK_AT},{_RECOINT_AT}); "
        f"got opens {opens_in_dead}"
    )
    # Re-enters only on/after the re-cointegration boundary.
    opens_after = [o for o in opens if o >= _RECOINT_AT]
    assert opens_after, (
        f"basket must re-enter after re-cointegration at {_RECOINT_AT}; opens={opens}"
    )
    assert min(opens_after) >= _RECOINT_AT, (
        f"first re-entry {min(opens_after)} must be on/after the latch reset {_RECOINT_AT}"
    )
    # The latch was cleared (we ended in a cointegrated regime + re-traded).
    assert rule._regime_broken is False, "latch must clear once regime re-cointegrates"


# --------------------------------------------------------------------------- #
# C2. Multi-break FSM: two full break-and-recovery cycles. The latch must SET
#     and CLEAR twice -- a finite-state machine, not a one-shot reset.
# --------------------------------------------------------------------------- #

def test_C2_multibreak_fsm():
    """regime: cointegrated -> 'breaking' (90, basket open) -> 'broken' (91) ->
    'cointegrated' (122) -> 'breaking' (150, basket open) -> 'cointegrated' (160).

    Test C exercises ONE break + ONE recovery, so it cannot tell a real FSM from
    a one-shot reset: a latch that resets exactly once would pass C identically.
    This case threads TWO break-and-recovery cycles through the SAME baseline
    trajectory and asserts the `_regime_broken` latch SETS and CLEARS twice:

      BREAK #1    (loc 90, inside the open 84..102 span): regime-break liquidation,
                  latch SETS.
      RE-COINT #1 (loc 122, flat gap before the 126 open): latch CLEARS, basket
                  re-enters on/after 122 -- the first re-entry is loc 126.
      BREAK #2    (loc 150, inside the open 146..166 span): a SECOND, distinct
                  regime-break liquidation -- the latch must re-SET after having
                  been cleared once (the discriminating step vs a one-shot).
      RE-COINT #2 (loc 160, flat gap before the 170 open): latch CLEARS AGAIN,
                  basket re-enters on/after 160 -- the first re-entry is loc 170.

    A one-shot reset FAILS here: either BREAK #2 produces no exit (the latch never
    re-set after the first reset) or RE-COINT #2 produces no re-entry (the reset
    fired only once). Both are real FSM bugs in the latch logic, not test noise."""
    transitions = [
        (_FSM_BREAK_1,   "breaking"),
        (_FSM_BROKEN_1,  "broken"),
        (_FSM_RECOINT_1, "cointegrated"),
        (_FSM_BREAK_2,   "breaking"),
        (_FSM_RECOINT_2, "cointegrated"),
    ]
    rule, legA, legB = _run(True, regime_transitions=transitions)

    # Sanity: the six injected regime phases landed on the values/locs we placed.
    assert legA.df.iloc[_FSM_BREAK_1]["coint_regime"] == "breaking"
    assert legA.df.iloc[_FSM_BROKEN_1]["coint_regime"] == "broken"
    assert legA.df.iloc[_FSM_RECOINT_1]["coint_regime"] == "cointegrated"
    assert legA.df.iloc[_FSM_BREAK_2]["coint_regime"] == "breaking"
    assert legA.df.iloc[_FSM_RECOINT_2]["coint_regime"] == "cointegrated"

    # --- TWO distinct regime-break liquidations, at the two breaking-bar locs. ---
    breaks = _break_liqs(rule, legA)
    assert breaks == [_FSM_BREAK_1, _FSM_BREAK_2], (
        f"expected exactly TWO regime-break liquidations at the two breaking bars "
        f"{[_FSM_BREAK_1, _FSM_BREAK_2]} -- a one-shot latch that does NOT re-set "
        f"after the first reset would miss the second exit; got {breaks}"
    )
    # Each break is tagged LIQUIDATE_REGIME_BREAK and leaves the basket flat.
    for loc in (_FSM_BREAK_1, _FSM_BREAK_2):
        rec = next(r for r in rule.per_bar_records if _loc(legA, r["timestamp"]) == loc)
        assert rec["skip_reason"] == "LIQUIDATE_REGIME_BREAK", (
            f"break bar {loc} must carry skip_reason=LIQUIDATE_REGIME_BREAK; "
            f"got {rec['skip_reason']!r}"
        )
        assert rec["active_legs"] == 0, f"basket must be flat on break bar {loc}"

    opens = _opens(rule, legA)

    # --- FLAT throughout BOTH non-cointegrated spans (no re-entry mid-break). ---
    # Dead span 1: [BREAK_1, RECOINT_1)  (breaking+broken before the first recovery).
    dead1 = [o for o in opens if _FSM_BREAK_1 <= o < _FSM_RECOINT_1]
    assert dead1 == [], (
        f"basket must stay flat through the first breaking/broken span "
        f"[{_FSM_BREAK_1},{_FSM_RECOINT_1}); got opens {dead1}"
    )
    # Dead span 2: [BREAK_2, RECOINT_2)  (the second breaking span).
    dead2 = [o for o in opens if _FSM_BREAK_2 <= o < _FSM_RECOINT_2]
    assert dead2 == [], (
        f"basket must stay flat through the second breaking span "
        f"[{_FSM_BREAK_2},{_FSM_RECOINT_2}); got opens {dead2}"
    )

    # --- RE-ENTRY #1: only on/after RECOINT_1, and strictly before BREAK_2. ---
    reentry1 = [o for o in opens if _FSM_RECOINT_1 <= o < _FSM_BREAK_2]
    assert reentry1, (
        f"basket must RE-ENTER after the first re-cointegration {_FSM_RECOINT_1} "
        f"(latch cleared the FIRST time); opens={opens}"
    )
    assert min(reentry1) >= _FSM_RECOINT_1, (
        f"first re-entry {min(reentry1)} must be on/after the first latch reset "
        f"{_FSM_RECOINT_1}, NOT before"
    )

    # --- RE-ENTRY #2: only on/after RECOINT_2 -- proves the reset is NOT one-shot. ---
    reentry2 = [o for o in opens if o >= _FSM_RECOINT_2]
    assert reentry2, (
        f"basket must RE-ENTER AGAIN after the second re-cointegration "
        f"{_FSM_RECOINT_2} -- a one-shot reset would never re-enable entry the "
        f"second time; opens={opens}"
    )
    assert min(reentry2) >= _FSM_RECOINT_2, (
        f"second re-entry {min(reentry2)} must be on/after the second latch reset "
        f"{_FSM_RECOINT_2}, NOT before"
    )

    # >= 2 BASKET_OPEN cycles, each opening only within a cointegrated span.
    assert len(reentry1) + len(reentry2) >= 2, (
        f"expected >=2 re-entry cycles across the two cointegrated spans; "
        f"got cycle1={reentry1} cycle2={reentry2}"
    )

    # The latch ended CLEARED (we finished in a cointegrated regime and re-traded).
    assert rule._regime_broken is False, (
        "latch must end CLEARED after the second re-cointegration (FSM, not stuck-set)"
    )


# --------------------------------------------------------------------------- #
# D. flag OFF (and unset): byte-identical to the NO-regime-column baseline.
# --------------------------------------------------------------------------- #

def test_D_flag_off_byte_identical():
    """coint_break_exit=False (and UNSET) must be BYTE-IDENTICAL to the baseline
    rule run with NO `coint_regime` column at all -- proving the gate (break-exit,
    latch, AND latch-reset) is fully INERT when the flag is off, even when a
    break-laden regime column is present. A divergence here would mean the join
    or the latch-reset leaked into the flag-off path."""
    # Baseline: no regime column whatsoever.
    r_base, _, _ = _run(False, attach_regime=False)
    # Flag off, UNSET (dataclass default), with a break-laden regime present.
    break_laden = [(_BREAK_AT, "breaking"), (_BROKEN_FROM, "broken"),
                   (_RECOINT_AT, "cointegrated")]
    r_unset, _, _ = _run(None, regime_transitions=break_laden)
    # Flag off, EXPLICIT False, same break-laden regime.
    r_off, _, _ = _run(False, regime_transitions=break_laden)

    assert r_unset.coint_break_exit is False, "unset flag must default False"
    assert sum(1 for e in r_base.recycle_events if e["action"] == "BASKET_OPEN") >= 3

    # No break event in ANY flag-off run, regardless of the regime column.
    for r in (r_base, r_unset, r_off):
        assert not any(e.get("reason") == "REGIME_BREAK" for e in r.recycle_events)
        assert r._regime_broken is False

    # Byte-identical events + records: baseline == unset == explicit-off.
    assert r_base.recycle_events == r_unset.recycle_events == r_off.recycle_events, (
        "recycle_events diverged across flag-off variants -- the gate is NOT inert"
    )
    nb = _normalize_nan(r_base.per_bar_records)
    assert nb == _normalize_nan(r_unset.per_bar_records) == _normalize_nan(r_off.per_bar_records), (
        "per_bar_records diverged across flag-off variants -- the gate is NOT inert"
    )
