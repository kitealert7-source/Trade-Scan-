"""Unit tests for PineRatioZRevRule._granular_parity_lots (sizing_mode=granular_parity).

Granular notional parity picks integer lot-step multiples (k_a,k_b) in
[1, granular_parity_max_k] minimizing the leg notional imbalance, tiebreaking
toward fewer total lots. Replaces the lot-equal-floor degradation of the plain
notional mode at small targets (~44% median imbalance -> ~3%). Validated
end-to-end 2026-06-03 (AUS200/JPN225: 56% -> 2%)."""
from __future__ import annotations
import sys
from types import SimpleNamespace
from pathlib import Path
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule  # noqa: E402

BAR = pd.Timestamp("2024-07-19 10:00", tz="UTC")


def _leg(sym, close):
    df = pd.DataFrame({"close": [close]}, index=pd.DatetimeIndex([BAR]))
    return SimpleNamespace(symbol=sym, df=df)


def _specs(a, b):
    # usd_per_pu=1 so step-notional == lot_step*price; min_lot=lot_step=0.01
    return {a: {"usd_per_pu": 1.0, "min_lot": 0.01, "lot_step": 0.01},
            b: {"usd_per_pu": 1.0, "min_lot": 0.01, "lot_step": 0.01}}


def test_picks_parity_minimizing_integers():
    # step-notional A=100, B=175 -> ratio 1.75; best small k_a/k_b ~ 7/4 (=1.75 exact)
    rule = PineRatioZRevRule(sizing_mode="granular_parity", granular_parity_max_k=8)
    legs = [_leg("AAA", 100.0), _leg("BBB", 175.0)]
    sp = _specs("AAA", "BBB")
    out = rule._granular_parity_lots(legs, BAR, {"AAA": 0.01, "BBB": 0.01}, sp)
    na, nb = out["AAA"] * 100.0, out["BBB"] * 175.0
    imb = abs(na - nb) / max(na, nb)
    assert imb < 0.05, f"granular parity should be <5% imbalance, got {imb:.2%} ({out})"
    # and it must beat lot-equal (0.01/0.01 -> |100-175|/175 = 43%)
    assert imb < 0.43


def test_equal_step_notional_stays_lot_equal():
    # identical step-notionals -> (1,1) is already parity; tiebreak keeps it minimal
    rule = PineRatioZRevRule(sizing_mode="granular_parity", granular_parity_max_k=8)
    legs = [_leg("AAA", 100.0), _leg("BBB", 100.0)]
    out = rule._granular_parity_lots(legs, BAR, {"AAA": 0.01, "BBB": 0.01}, _specs("AAA", "BBB"))
    assert out == {"AAA": 0.01, "BBB": 0.01}


def test_fallback_to_notional_on_bad_price():
    rule = PineRatioZRevRule(sizing_mode="granular_parity")
    legs = [_leg("AAA", 0.0), _leg("BBB", 175.0)]   # price<=0 -> fallback
    nl = {"AAA": 0.02, "BBB": 0.03}
    out = rule._granular_parity_lots(legs, BAR, nl, _specs("AAA", "BBB"))
    assert out == nl


def test_max_k_caps_the_search():
    # ratio 1.75 with max_k=2 cannot hit 7/4; best within {1,2}^2 is (2,1)=2.0 (imb 0.125)
    rule = PineRatioZRevRule(sizing_mode="granular_parity", granular_parity_max_k=2)
    legs = [_leg("AAA", 100.0), _leg("BBB", 175.0)]
    out = rule._granular_parity_lots(legs, BAR, {"AAA": 0.01, "BBB": 0.01}, _specs("AAA", "BBB"))
    assert max(out.values()) <= 0.02 + 1e-9


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
