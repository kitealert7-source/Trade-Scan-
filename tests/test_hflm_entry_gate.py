"""Validation suite for the HF-intersect-LM entry filter
(pine_ratio_zrev_v1_zcross_hflm, 2026-06-12, HFLM arm).

Blocks ONLY when BOTH detectors agree: Hurst(ratio) > hurst_block_above AND
max-leg net move > lm_block_above. Harness mirrors the HF/HL/LM gate suites.

Cases:
  PARITY    -- EITHER threshold beyond reach (math.inf) => the AND never fires
               => byte-identical champion, both fill timings (asserted for the
               HF side AND the LM side, since either disables the gate).
  FIRES     -- both thresholds low enough that some entry satisfies both:
               >=1 BOTH_BLOCK, counter matches, telemetry carries h>thr AND
               mm>thr, no opens on blocked bars.
  AND-LOGIC -- an entry passing only ONE condition is NOT blocked (the
               distinguishing property vs the single-filter arms).
  PARAMS    -- constructor validation (all four bounds).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_rules.pine_ratio_zrev_v1_zcross_hflm import PineRatioZRevRuleZCrossHFLM
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0
HW = 50


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
        run_id="HFLMG", directive_id="HFLMG", basket_id="HFLMG", **extra,
    )
    BasketRunner([legA, legB], [rule],
                 warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    return rule, legA, legB


def _loc(leg, bar_ts):
    return leg.df.index.get_loc(bar_ts)


def _opens(rule, leg):
    return sorted(_loc(leg, e["bar_ts"]) for e in rule.recycle_events
                  if e.get("action") == "BASKET_OPEN")


# --------------------------------------------------------------------------- #
# PARITY — either threshold beyond reach disables the AND.
# --------------------------------------------------------------------------- #

def _assert_parity(exit_fill_timing, **disable):
    r_x, _, _ = _run(PineRatioZRevRuleZCrossHFLM, exit_fill_timing=exit_fill_timing, **disable)
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing=exit_fill_timing)
    assert sum(1 for e in r_c.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    assert not any(e.get("action") == "BOTH_BLOCK" for e in r_x.recycle_events)
    assert r_x._n_both_blocks == 0
    assert r_x.recycle_events == r_c.recycle_events
    assert _normalize_nan(r_x.per_bar_records) == _normalize_nan(r_c.per_bar_records)


def test_parity_hurst_disabled_next_open():
    _assert_parity("next_open", hurst_block_above=math.inf, lm_block_above=0.5)


def test_parity_lm_disabled_bar_close():
    _assert_parity("bar_close", hurst_block_above=0.3, lm_block_above=math.inf)


# --------------------------------------------------------------------------- #
# FIRES + AND-LOGIC
# --------------------------------------------------------------------------- #

def test_hflm_blocks_only_on_agreement():
    """Low thresholds on both sides -> some entries satisfy BOTH -> BOTH_BLOCK
    fires; every block carries h>thr AND mm>thr; no opens on blocked bars."""
    # Probe both series at the champion open bars (parity-mode HFLM run).
    r_p, legAp, _ = _run(PineRatioZRevRuleZCrossHFLM,
                         hurst_block_above=math.inf, lm_block_above=math.inf)
    h = legAp.df["pine_zrev_hurst"]
    mm = legAp.df["pine_zrev_legmove"]
    opens = _opens(r_p, legAp)
    assert opens, "fixture must open baskets"
    h_at = h.iloc[opens].dropna()
    mm_at = mm.iloc[opens].dropna()
    assert not h_at.empty and not mm_at.empty
    # Thresholds at the medians so a meaningful subset clears BOTH.
    h_thr = round(float(h_at.median()), 4)
    mm_thr = round(float(mm_at.median()), 4)

    rule, legA2, _ = _run(PineRatioZRevRuleZCrossHFLM,
                          hurst_block_above=h_thr, lm_block_above=mm_thr)
    blocks = [e for e in rule.recycle_events if e.get("action") == "BOTH_BLOCK"]
    assert blocks, f"expected >=1 BOTH_BLOCK at h>{h_thr} & mm>{mm_thr}"
    assert rule._n_both_blocks == len(blocks)
    for e in blocks:
        assert e["h"] > h_thr and e["mm"] > mm_thr           # AND satisfied
        assert e["h_threshold"] == h_thr and e["mm_threshold"] == mm_thr
        assert e["leg"] in (SYM_A, SYM_B)
        assert e["direction"] in (+1, -1)
    open_locs = set(_opens(rule, legA2))
    block_locs = {_loc(legA2, e["bar_ts"]) for e in blocks}
    assert open_locs.isdisjoint(block_locs)


def test_single_condition_does_not_block():
    """An impossibly-high LM threshold with a low Hurst threshold: the HF
    condition fires constantly but the AND never does -> zero blocks, parity
    with champion. (The distinguishing property vs the HF-only arm.)"""
    r_x, _, _ = _run(PineRatioZRevRuleZCrossHFLM,
                     hurst_block_above=0.0001, lm_block_above=1e9)
    r_c, _, _ = _run(PineRatioZRevRuleZCross)
    assert r_x._n_both_blocks == 0
    assert r_x.recycle_events == r_c.recycle_events


# --------------------------------------------------------------------------- #
# PARAMS
# --------------------------------------------------------------------------- #

def test_param_validation():
    for kw in ({"hurst_window": 5}, {"lm_window": 1},
               {"hurst_block_above": 0.0}, {"lm_block_above": 0.0}):
        with pytest.raises(ValueError):
            PineRatioZRevRuleZCrossHFLM(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                       entry_mode="absolute", **kw)
