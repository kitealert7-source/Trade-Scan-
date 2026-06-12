"""Validation suite for the leg-displacement entry-filter overlay
(pine_ratio_zrev_v1_zcross_lm, 2026-06-12, LM20 arm).

The LM variant is the ZCRS champion PLUS an entry block: proposals are refused
when EITHER leg's vol-scaled trailing net move (normalized_net_move) exceeds
lm_block_above at the signal bar ("don't fade large directional repricings").

Harness mirrors tests/test_hurst_entry_gate.py / test_hl_entry_gate.py.

Cases:
  PARITY    -- lm_block_above = math.inf == the zcross champion, byte-identical,
               both exit_fill_timing modes.
  FIRES     -- threshold inside the fixture's nnm range: >=1 MOVE_BLOCK
               (premise-checked), counter matches, every event carries
               mm > threshold + the driving leg symbol, no opens on blocked bars.
  FAIL-OPEN -- lm_min_vol_obs larger than the data (nnm all-NaN): identical to
               the champion; zero blocks.
  PARAMS    -- constructor validation.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_rules.pine_ratio_zrev_v1_zcross_lm import PineRatioZRevRuleZCrossLM
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
        run_id="LMG", directive_id="LMG", basket_id="LMG", **extra,
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
# PARITY
# --------------------------------------------------------------------------- #

def _assert_parity(exit_fill_timing):
    r_l, _, _ = _run(PineRatioZRevRuleZCrossLM, exit_fill_timing=exit_fill_timing,
                     lm_block_above=math.inf)
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing=exit_fill_timing)

    assert sum(1 for e in r_c.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    assert not any(e.get("action") == "MOVE_BLOCK" for e in r_l.recycle_events)
    assert r_l._n_move_blocks == 0
    assert r_l.recycle_events == r_c.recycle_events
    assert _normalize_nan(r_l.per_bar_records) == _normalize_nan(r_c.per_bar_records)


def test_parity_next_open():
    _assert_parity("next_open")


def test_parity_bar_close():
    _assert_parity("bar_close")


# --------------------------------------------------------------------------- #
# FIRES
# --------------------------------------------------------------------------- #

def test_lm_gate_blocks_and_records_telemetry():
    """Probe the parity run's nnm at its open bars, pick a reachable finite
    threshold, assert blocks fire with honest telemetry."""
    r_p, legAp, _ = _run(PineRatioZRevRuleZCrossLM, lm_block_above=math.inf)
    mm_col = legAp.df["pine_zrev_legmove"]
    champion_opens = _opens(r_p, legAp)
    assert champion_opens, "fixture must open baskets in parity mode"

    mm_at_opens = mm_col.iloc[champion_opens].dropna()
    assert not mm_at_opens.empty, "no valid nnm at any open bar"
    thr = round(float(mm_at_opens.min() + 0.5 * (mm_at_opens.max() - mm_at_opens.min())), 4)
    if thr <= 0 or thr >= float(mm_at_opens.max()):
        thr = round(float(mm_at_opens.median()), 4)
    assert 0 < thr < float(mm_at_opens.max())

    rule, legA2, _ = _run(PineRatioZRevRuleZCrossLM, lm_block_above=thr)
    blocks = [e for e in rule.recycle_events if e.get("action") == "MOVE_BLOCK"]
    assert blocks, f"expected >=1 MOVE_BLOCK at threshold {thr}"
    assert rule._n_move_blocks == len(blocks)

    for e in blocks:
        assert e["mm"] == e["mm"] and e["mm"] > thr
        assert e["threshold"] == thr
        assert e["leg"] in (SYM_A, SYM_B)
        assert e["direction"] in (+1, -1)

    open_locs = set(_opens(rule, legA2))
    block_locs = {_loc(legA2, e["bar_ts"]) for e in blocks}
    assert open_locs.isdisjoint(block_locs)
    assert open_locs != set(champion_opens)


# --------------------------------------------------------------------------- #
# FAIL-OPEN
# --------------------------------------------------------------------------- #

def test_fail_open_when_nnm_unavailable():
    """lm_min_vol_obs beyond the data leaves nnm NaN everywhere: identical to
    the champion, zero blocks."""
    r_l, _, _ = _run(PineRatioZRevRuleZCrossLM,
                     lm_min_vol_obs=N_BARS + 50, lm_block_above=2.0)
    r_c, _, _ = _run(PineRatioZRevRuleZCross)
    assert r_l._n_move_blocks == 0
    assert not any(e.get("action") == "MOVE_BLOCK" for e in r_l.recycle_events)
    assert r_l.recycle_events == r_c.recycle_events
    assert _normalize_nan(r_l.per_bar_records) == _normalize_nan(r_c.per_bar_records)


# --------------------------------------------------------------------------- #
# PARAMS
# --------------------------------------------------------------------------- #

def test_param_validation():
    with pytest.raises(ValueError, match="lm_window"):
        PineRatioZRevRuleZCrossLM(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                  entry_mode="absolute", lm_window=1)
    with pytest.raises(ValueError, match="lm_block_above"):
        PineRatioZRevRuleZCrossLM(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                  entry_mode="absolute", lm_block_above=0.0)
