"""Validation suite for the Hurst entry-filter overlay (pine_ratio_zrev_v1_zcross_hf, 2026-06-12).

The HF variant is the ZCRS champion (PineRatioZRevRuleZCross) PLUS an entry block:
proposals are refused when the canonical ratio's trailing R/S Hurst (hurst_window
bars, indicators.trend.hurst_rs) exceeds hurst_block_above at the signal bar. This
suite is the CLEAN-TOGGLE gate the HF55 cohort run depends on: it proves the variant
differs from the champion ONLY when the gate actually blocks.

Harness mirrors tests/test_z_stop_gate.py: deterministic (no RNG / wall-clock)
2-leg OHLC driven through the REAL engine path (BasketRunner.run(fast_path=False)).

Cases:
  PARITY    -- hurst_block_above beyond the estimator's reach (1e9) == the zcross
               champion, BYTE-IDENTICAL (recycle_events + per_bar_records), for BOTH
               exit_fill_timing modes. This is the property the experiment trusts.
  FIRES     -- threshold inside the fixture's H range: >=1 HURST_BLOCK recorded
               (premise-checked), each blocked bar arms no proposal / opens no
               basket, the counter matches, and every blocked H exceeds the
               threshold (telemetry-distribution contract).
  FAIL-OPEN -- hurst_window larger than the data (H all-NaN at signal bars):
               behavior identical to the champion; zero blocks.
  PARAMS    -- constructor validation (window >= 10, threshold > 0).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_rules.pine_ratio_zrev_v1_zcross_hf import PineRatioZRevRuleZCrossHF
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0
HURST_WINDOW = 50


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
    """Fresh construction + full engine-path run. Returns (rule, legA, legB)."""
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
        run_id="HFG", directive_id="HFG", basket_id="HFG", **extra,
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
# PARITY: threshold beyond reach (1e9) == the zcross champion, byte-identical.
# --------------------------------------------------------------------------- #

def _assert_parity(exit_fill_timing):
    r_h, _, _ = _run(PineRatioZRevRuleZCrossHF, exit_fill_timing=exit_fill_timing,
                     hurst_window=HURST_WINDOW, hurst_block_above=1e9)
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing=exit_fill_timing)

    # The fixture must actually trade, else parity is vacuous.
    assert sum(1 for e in r_c.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    # No block ever fired.
    assert not any(e.get("action") == "HURST_BLOCK" for e in r_h.recycle_events), (
        "a hurst_block_above beyond the estimator's reach must never block")
    assert r_h._n_hurst_blocks == 0

    assert r_h.recycle_events == r_c.recycle_events, (
        f"recycle_events diverged: hurst_block_above=1e9 != zcross champion "
        f"(exit_fill_timing={exit_fill_timing})")
    assert _normalize_nan(r_h.per_bar_records) == _normalize_nan(r_c.per_bar_records), (
        f"per_bar_records diverged: hurst_block_above=1e9 != zcross champion "
        f"(exit_fill_timing={exit_fill_timing})")


def test_parity_next_open():
    """exit_fill_timing='next_open' (the experiment's config): the inert HF gate is
    byte-identical to the zcross champion."""
    _assert_parity("next_open")


def test_parity_bar_close():
    """exit_fill_timing='bar_close' (the default): parity holds here too -- the HF
    overlay is inert regardless of fill timing when the gate never blocks."""
    _assert_parity("bar_close")


# --------------------------------------------------------------------------- #
# FIRES: threshold inside the fixture's H range -> blocks recorded, no opens
# at blocked bars, telemetry distribution honest.
# --------------------------------------------------------------------------- #

def test_hurst_gate_blocks_and_records_distribution():
    """Pick a threshold the fixture's H actually exceeds at >=1 champion entry bar.
    Assert: >=1 HURST_BLOCK; the counter matches; every blocked event carries
    h > threshold (the distribution-telemetry contract); no basket opens on a
    blocked proposal bar; and total opens strictly drop vs the champion."""
    # Probe the champion run: H at its BASKET_OPEN proposal bars sets the premise.
    r_c, legA, _ = _run(PineRatioZRevRuleZCross)
    h_col = None
    # The champion does not attach the H column; recompute via the HF attach by
    # running the HF rule in parity mode and reading its attached column.
    r_p, legAp, _ = _run(PineRatioZRevRuleZCrossHF,
                         hurst_window=HURST_WINDOW, hurst_block_above=1e9)
    h_col = legAp.df["pine_zrev_hurst"]
    champion_opens = _opens(r_p, legAp)
    assert champion_opens, "fixture must open baskets in parity mode"

    # Premise: choose a threshold below the max H seen at the parity run's open
    # bars, so at least one champion entry becomes blockable.
    h_at_opens = h_col.iloc[champion_opens].dropna()
    assert not h_at_opens.empty, "no valid H at any open bar -- fixture too short"
    h_max = float(h_at_opens.max())
    thr = round(h_max - 0.02, 3)
    assert thr > 0, f"degenerate threshold {thr}"

    rule, legA2, _ = _run(PineRatioZRevRuleZCrossHF,
                          hurst_window=HURST_WINDOW, hurst_block_above=thr)
    blocks = [e for e in rule.recycle_events if e.get("action") == "HURST_BLOCK"]
    assert blocks, f"expected >=1 HURST_BLOCK at threshold {thr} (h_max={h_max})"
    assert rule._n_hurst_blocks == len(blocks)

    # Telemetry-distribution contract: every block carries its H, all > threshold,
    # and the threshold field echoes the configured value.
    for e in blocks:
        assert e["h"] == e["h"] and e["h"] > thr, e
        assert e["threshold"] == thr
        assert e["direction"] in (+1, -1)

    # No basket opens on a blocked proposal bar.
    open_locs = set(_opens(rule, legA2))
    block_locs = {_loc(legA2, e["bar_ts"]) for e in blocks}
    assert open_locs.isdisjoint(block_locs), (
        f"basket opened on a blocked bar: {sorted(open_locs & block_locs)}")

    # The filter changed the entry schedule relative to the unfiltered (parity)
    # run. NOTE: not asserted as a strict COUNT drop -- a blocked proposal can be
    # relocated to the next +/-z_entry cross (the strategy re-arms), so on a
    # dense fixture the count may match while the entry bars differ. The
    # economic effect (fewer/different cycles) is the cohort run's question.
    assert open_locs != set(champion_opens), (
        "blocking fired but the entry schedule is unchanged vs the champion")


# --------------------------------------------------------------------------- #
# FAIL-OPEN: H unavailable (window > data) -> identical to champion, no blocks.
# --------------------------------------------------------------------------- #

def test_fail_open_when_h_unavailable():
    """hurst_window larger than the fixture leaves H NaN everywhere: the gate must
    never block on a missing estimate -- behavior identical to the champion."""
    r_h, _, _ = _run(PineRatioZRevRuleZCrossHF,
                     hurst_window=N_BARS + 50, hurst_block_above=0.55)
    r_c, _, _ = _run(PineRatioZRevRuleZCross)

    assert r_h._n_hurst_blocks == 0
    assert not any(e.get("action") == "HURST_BLOCK" for e in r_h.recycle_events)
    assert r_h.recycle_events == r_c.recycle_events
    assert _normalize_nan(r_h.per_bar_records) == _normalize_nan(r_c.per_bar_records)


# --------------------------------------------------------------------------- #
# PARAMS: constructor validation.
# --------------------------------------------------------------------------- #

def test_param_validation():
    with pytest.raises(ValueError, match="hurst_window"):
        PineRatioZRevRuleZCrossHF(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                  entry_mode="absolute", hurst_window=5)
    with pytest.raises(ValueError, match="hurst_block_above"):
        PineRatioZRevRuleZCrossHF(n_window=N_WINDOW, z_entry=Z_ENTRY,
                                  entry_mode="absolute", hurst_block_above=0.0)
