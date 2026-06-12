"""Validation suite for the local half-life entry-filter overlay
(pine_ratio_zrev_v1_zcross_hl, 2026-06-12, HL120 arm).

The HL variant is the ZCRS champion PLUS an entry block: proposals are refused
when the canonical ratio's rolling AR(1) half-life (hl_window bars,
indicators.stats.rolling_half_life) exceeds hl_block_above bars or the window
is non-reverting (+inf). This suite is the CLEAN-TOGGLE gate the HL120 cohort
run depends on.

Harness mirrors tests/test_hurst_entry_gate.py (deterministic 2-leg OHLC via
the REAL engine path).

Cases:
  PARITY    -- hl_block_above = math.inf == the zcross champion, BYTE-IDENTICAL,
               both exit_fill_timing modes. (inf, not "very large": any finite
               threshold still blocks non-reverting windows.)
  FIRES     -- threshold inside the fixture's HL range: >=1 HL_BLOCK
               (premise-checked), counter matches, every blocked event carries
               hl > threshold OR non_reverting, no basket opens on blocked bars.
  FAIL-OPEN -- hl_window larger than the data (HL all-NaN): identical to the
               champion; zero blocks.
  PARAMS    -- constructor validation (window >= 20, threshold > 0).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_rules.pine_ratio_zrev_v1_zcross_hl import PineRatioZRevRuleZCrossHL
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0
HL_WINDOW = 100


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
        run_id="HLG", directive_id="HLG", basket_id="HLG", **extra,
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
# PARITY: hl_block_above = inf == the zcross champion, byte-identical.
# --------------------------------------------------------------------------- #

def _assert_parity(exit_fill_timing):
    r_h, _, _ = _run(PineRatioZRevRuleZCrossHL, exit_fill_timing=exit_fill_timing,
                     hl_window=HL_WINDOW, hl_block_above=math.inf)
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing=exit_fill_timing)

    assert sum(1 for e in r_c.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    assert not any(e.get("action") == "HL_BLOCK" for e in r_h.recycle_events)
    assert r_h._n_hl_blocks == 0
    assert r_h.recycle_events == r_c.recycle_events, (
        f"recycle_events diverged (exit_fill_timing={exit_fill_timing})")
    assert _normalize_nan(r_h.per_bar_records) == _normalize_nan(r_c.per_bar_records), (
        f"per_bar_records diverged (exit_fill_timing={exit_fill_timing})")


def test_parity_next_open():
    _assert_parity("next_open")


def test_parity_bar_close():
    _assert_parity("bar_close")


# --------------------------------------------------------------------------- #
# FIRES: threshold inside the fixture's HL range.
# --------------------------------------------------------------------------- #

def test_hl_gate_blocks_and_records_distribution():
    """Probe the parity run's HL at its open bars, choose a reachable finite
    threshold, and assert blocks fire with honest telemetry."""
    r_p, legAp, _ = _run(PineRatioZRevRuleZCrossHL,
                         hl_window=HL_WINDOW, hl_block_above=math.inf)
    hl_col = legAp.df["pine_zrev_half_life"]
    champion_opens = _opens(r_p, legAp)
    assert champion_opens, "fixture must open baskets in parity mode"

    hl_at_opens = hl_col.iloc[champion_opens]
    finite = hl_at_opens[np.isfinite(hl_at_opens)]
    assert not hl_at_opens.dropna().empty, "no valid HL at any open bar"
    # Threshold below the max observed (finite max if any, else any finite
    # value below inf works -- pick 1.0 above the min so something passes too).
    if not finite.empty and finite.max() > finite.min():
        thr = round(float(finite.min() + 0.5 * (finite.max() - finite.min())), 3)
    else:
        thr = 50.0  # all-inf at opens: any finite threshold blocks them
    assert thr > 0

    rule, legA2, _ = _run(PineRatioZRevRuleZCrossHL,
                          hl_window=HL_WINDOW, hl_block_above=thr)
    blocks = [e for e in rule.recycle_events if e.get("action") == "HL_BLOCK"]
    assert blocks, f"expected >=1 HL_BLOCK at threshold {thr}"
    assert rule._n_hl_blocks == len(blocks)

    for e in blocks:
        assert e["threshold"] == thr
        assert e["direction"] in (+1, -1)
        if e["non_reverting"]:
            assert e["hl"] is None          # +inf is carried as the flag
        else:
            assert e["hl"] is not None and e["hl"] > thr

    open_locs = set(_opens(rule, legA2))
    block_locs = {_loc(legA2, e["bar_ts"]) for e in blocks}
    assert open_locs.isdisjoint(block_locs), (
        f"basket opened on a blocked bar: {sorted(open_locs & block_locs)}")
    # Entry schedule changed (count may match due to relocation; see HF test).
    assert open_locs != set(champion_opens)


# --------------------------------------------------------------------------- #
# FAIL-OPEN: HL unavailable (window > data) -> identical to champion.
# --------------------------------------------------------------------------- #

def test_fail_open_when_hl_unavailable():
    r_h, _, _ = _run(PineRatioZRevRuleZCrossHL,
                     hl_window=N_BARS + 50, hl_block_above=120.0)
    r_c, _, _ = _run(PineRatioZRevRuleZCross)
    assert r_h._n_hl_blocks == 0
    assert not any(e.get("action") == "HL_BLOCK" for e in r_h.recycle_events)
    assert r_h.recycle_events == r_c.recycle_events
    assert _normalize_nan(r_h.per_bar_records) == _normalize_nan(r_c.per_bar_records)


# --------------------------------------------------------------------------- #
# PARAMS: constructor validation.
# --------------------------------------------------------------------------- #

def test_param_validation():
    with pytest.raises(ValueError, match="hl_window"):
        PineRatioZRevRuleZCrossHL(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                  entry_mode="absolute", hl_window=10)
    with pytest.raises(ValueError, match="hl_block_above"):
        PineRatioZRevRuleZCrossHL(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                  entry_mode="absolute", hl_block_above=0.0)
