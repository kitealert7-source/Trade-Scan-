"""Slice 2.5 -- operational dry loop: the whole chain under CONTINUOUS running.

Components are unit-proven (bridge, reconcile, driver, parity); these tests prove
the things that only appear when it RUNS continuously -- convergence every cycle,
restart resilience, both-legs-fresh no-ops, and that the running loop's emitted
target transitions still equal the batch (research == streaming, end to end).
Mock broker, no MT5.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.live_basket import bridge
from tools.live_basket.driver import target_sequence_from_records
from tools.live_basket.loop import run_dry_session
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS, N_WINDOW, Z_ENTRY = 100, 30, 1.0
BID = "LOOP"


def _ohlc(close, idx):
    close = np.asarray(close, float)
    openp = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": openp, "high": np.maximum(openp, close) * 1.00008,
                         "low": np.minimum(openp, close) * 0.99992, "close": close,
                         "volume": 1000.0, "spread": 0.00002}, index=idx)


def _synthetic_legs(n=N_BARS):
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    t = np.arange(n)
    osc = (0.60 * np.sin(2 * np.pi * t / 41) + 0.40 * np.sin(2 * np.pi * t / 17 + 0.7)
           + 0.25 * np.sin(2 * np.pi * t / 9 + 1.9) + 0.15 * np.sin(2 * np.pi * t / 5 + 0.3))
    return (_ohlc(1.1000 * (1 + 0.004 * osc), idx),
            _ohlc(1.2700 * (1 + 0.0005 * np.sin(2 * np.pi * t / 53)), idx))


def _replay(dfA, dfB):
    shared = PineZRevArmedState()
    lA = BasketLeg(SYM_A, 0.01, +1, dfA.copy(), PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    lB = BasketLeg(SYM_B, 0.01, -1, dfB.copy(), PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    rule = PineRatioZRevRuleZCross(n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute",
                                   shared_armed_state=shared, run_id="L", directive_id="L", basket_id=BID)
    BasketRunner([lA, lB], [rule], warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    return rule.per_bar_records


def _bridge_keys(bridge_dir):
    return [t.key for t in bridge.read_all_targets(bridge_dir)]


def _batch_keys(dfA, dfB):
    return [t.key for t in target_sequence_from_records(_replay(dfA, dfB), BID)]


# --------------------------------------------------------------------------- #

def test_continuous_run_matches_batch_and_converges(tmp_path):
    dfA, dfB = _synthetic_legs()
    out = run_dry_session(dfA, dfB, _replay, tmp_path, BID)
    decisions = [e["decision"] for e in out["log"]]

    # research == streaming, end to end through the RUNNING loop
    assert _bridge_keys(tmp_path) == _batch_keys(dfA, dfB)
    # it genuinely cycled, and never thrashed into incoherence (clean convergence)
    assert "NEED_OPEN" in decisions and "NEED_CLOSE" in decisions
    assert "INCOHERENT" not in decisions
    # ends converged: broker agrees with the final target
    final = bridge.read_latest_target(tmp_path)
    legs = out["broker"].read_positions()
    assert (legs == []) if final.state == "FLAT" else (len(legs) == 2)


def test_driver_restart_is_transparent_and_emits_no_duplicate(tmp_path):
    dfA, dfB = _synthetic_legs()
    run_dry_session(dfA, dfB, _replay, tmp_path, BID, restart_at=N_BARS // 2)

    keys = _bridge_keys(tmp_path)
    # restart is transparent: the running loop's transitions still equal batch
    assert keys == _batch_keys(dfA, dfB)
    # and the bridge-restore prevented a redundant emit: no two CONSECUTIVE targets
    # share a key (append-on-change held across the restart)
    assert all(keys[i] != keys[i - 1] for i in range(1, len(keys))), \
        "consecutive duplicate target -> driver re-emitted on restart (restore failed)"


def test_both_legs_fresh_gate_no_ops_on_stale_bar(tmp_path):
    dfA, dfB = _synthetic_legs()
    fresh = [True] * N_BARS
    for c in (70, 71, 95):                 # a few non-fresh bars (gap / stale leg)
        fresh[c] = False
    out = run_dry_session(dfA, dfB, _replay, tmp_path, BID, fresh_mask=fresh)

    # a non-fresh bar takes no action ...
    assert not any(e["bar"] in (70, 71, 95) for e in out["log"])
    # ... and the gate does not corrupt the sequence: transitions still match batch
    assert _bridge_keys(tmp_path) == _batch_keys(dfA, dfB)
    assert "INCOHERENT" not in [e["decision"] for e in out["log"]]
