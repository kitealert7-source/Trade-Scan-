"""Validation suite for the intraday UTC session-window overlay
(pine_ratio_zrev_v1_session_window, 2026-06-14).

Entries FILL only when the fill bar's UTC hour is in [entry_open_hour,
force_flat_hour); ALL open positions force-flat at force_flat_hour. Harness mirrors
the HF/HL/LM entry-gate suites (synthetic 5-min legs from 2024-01-01, so bar
timestamps sweep all 24 UTC hours).

Cases:
  PARITY     -- entry_open_hour=0, force_flat_hour=24 => both gates inert =>
                byte-identical champion (recycle_events + per_bar_records), both
                fill timings.
  FORCE-FLAT -- a basket held across an hour boundary is liquidated to flat
                (LIQUIDATE_SESSION_FLAT) at that hour; nothing is HELD at/after
                force_flat_hour.
  ENTRY-GATE -- every BASKET_OPEN (fill bar) lands inside [entry_open_hour,
                force_flat_hour); nothing is held outside the window.
  PARAMS     -- constructor validation (ordering + bounds + int type).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_rules.pine_ratio_zrev_v1_session_window import (
    PineRatioZRevRuleSessionWindow,
)
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0


def _ohlc(close, idx):
    close = np.asarray(close, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * 1.00008
    low = np.minimum(openp, close) * 0.99992
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close,
         "volume": 1000.0, "spread": 0.00002}, index=idx,
    )


def _synthetic_legs(n=N_BARS):
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    t = np.arange(n)
    osc = (0.60 * np.sin(2 * np.pi * t / 41)
           + 0.40 * np.sin(2 * np.pi * t / 17 + 0.7)
           + 0.25 * np.sin(2 * np.pi * t / 9 + 1.9)
           + 0.15 * np.sin(2 * np.pi * t / 5 + 0.3))
    return (_ohlc(1.1000 * (1.0 + 0.004 * osc), idx),
            _ohlc(1.2700 * (1.0 + 0.0005 * np.sin(2 * np.pi * t / 53)), idx))


def _normalize_nan(records):
    out = []
    for r in records:
        out.append({k: ("__NAN__" if isinstance(v, float) and math.isnan(v) else v)
                    for k, v in r.items()})
    return out


def _run(rule_cls, *, exit_fill_timing="next_open", **extra):
    dfA, dfB = _synthetic_legs()
    dfA, dfB = dfA.copy(), dfB.copy()
    dfA["coint_regime"] = "cointegrated"
    dfB["coint_regime"] = "cointegrated"
    shared = PineZRevArmedState()
    legA = BasketLeg(SYM_A, 0.01, +1, dfA, PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    legB = BasketLeg(SYM_B, 0.01, -1, dfB, PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    rule = rule_cls(
        n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute",
        exit_fill_timing=exit_fill_timing, shared_armed_state=shared,
        run_id="SESSG", directive_id="SESSG", basket_id="SESSG", **extra,
    )
    BasketRunner([legA, legB], [rule],
                 warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    return rule, legA, legB


def _opens(rule):
    return [e for e in rule.recycle_events if e.get("action") == "BASKET_OPEN"]


def _session_flats(rule):
    return [e for e in rule.recycle_events
            if e.get("action") == "LIQUIDATE" and e.get("reason") == "SESSION_FLAT"]


def _held(rule):
    return [r for r in rule.per_bar_records
            if r.get("active_legs", 0) and r.get("skip_reason") == "HOLDING"]


# --------------------------------------------------------------------------- #
# PARITY — full-day window (0, 24): both gates inert => byte-identical champion.
# --------------------------------------------------------------------------- #

def _assert_parity(exit_fill_timing):
    r_s, _, _ = _run(PineRatioZRevRuleSessionWindow, exit_fill_timing=exit_fill_timing,
                     entry_open_hour=0, force_flat_hour=24)
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing=exit_fill_timing)
    assert sum(1 for e in r_c.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    assert r_s._n_session_flats == 0
    assert not _session_flats(r_s)
    assert r_s.recycle_events == r_c.recycle_events
    assert _normalize_nan(r_s.per_bar_records) == _normalize_nan(r_c.per_bar_records)


def test_parity_full_day_next_open():
    _assert_parity("next_open")


def test_parity_full_day_bar_close():
    _assert_parity("bar_close")


# --------------------------------------------------------------------------- #
# FORCE-FLAT — held-across-boundary basket is flattened; nothing held at/after.
# --------------------------------------------------------------------------- #

def test_force_flat_fires_and_clears():
    # Data-driven: find an hour boundary the champion holds across, force-flat there.
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing="bar_close")
    recs = r_c.per_bar_records
    ffh = next(
        (b["timestamp"].hour for a, b in zip(recs, recs[1:])
         if a.get("active_legs") and b.get("active_legs")
         and a.get("skip_reason") == "HOLDING" and b.get("skip_reason") == "HOLDING"
         and a["timestamp"].hour != b["timestamp"].hour and b["timestamp"].hour > 0),
        None,
    )
    assert ffh is not None, "champion fixture must hold across an hour boundary"

    r_s, _, _ = _run(PineRatioZRevRuleSessionWindow, exit_fill_timing="bar_close",
                     entry_open_hour=0, force_flat_hour=ffh)
    flats = _session_flats(r_s)
    assert len(flats) == r_s._n_session_flats >= 1, f"expected >=1 SESSION_FLAT at ffh={ffh}"
    # No position is HELD at/after the force-flat hour.
    assert not [r for r in _held(r_s) if r["timestamp"].hour >= ffh], \
        f"position held at/after force_flat_hour={ffh}"


def test_no_overnight_hold_default_window():
    """Default-ish window (0, 21): nothing is held at/after 21:00 UTC."""
    r_s, _, _ = _run(PineRatioZRevRuleSessionWindow, exit_fill_timing="bar_close",
                     entry_open_hour=0, force_flat_hour=21)
    assert not [r for r in _held(r_s) if r["timestamp"].hour >= 21], \
        "position held at/after force_flat_hour=21"


# --------------------------------------------------------------------------- #
# ENTRY-GATE — every fill lands inside the window; nothing held outside it.
# --------------------------------------------------------------------------- #

def test_entry_gate_confines_fills_and_holds():
    EOH, FFH = 6, 18
    r_s, _, _ = _run(PineRatioZRevRuleSessionWindow, exit_fill_timing="bar_close",
                     entry_open_hour=EOH, force_flat_hour=FFH)
    open_hours = [e["bar_ts"].hour for e in _opens(r_s)]
    assert open_hours, "fixture must open >=1 basket inside the [6,18) window"
    assert all(EOH <= h < FFH for h in open_hours), f"out-of-window fills: {sorted(set(open_hours))}"
    # No position HELD outside [EOH, FFH).
    bad = [r["timestamp"] for r in _held(r_s) if not (EOH <= r["timestamp"].hour < FFH)]
    assert not bad, f"position held outside [{EOH},{FFH}): {bad[:3]}"


# --------------------------------------------------------------------------- #
# PARAMS
# --------------------------------------------------------------------------- #

def test_param_validation():
    base = dict(n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute")
    for kw in ({"entry_open_hour": 21, "force_flat_hour": 21},   # not strictly <
               {"entry_open_hour": 22, "force_flat_hour": 21},   # reversed
               {"entry_open_hour": -1, "force_flat_hour": 21},   # below 0
               {"entry_open_hour": 0, "force_flat_hour": 25}):    # above 24
        with pytest.raises(ValueError):
            PineRatioZRevRuleSessionWindow(**base, **kw)
