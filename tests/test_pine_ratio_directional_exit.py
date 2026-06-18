"""Direction-aware EXIT fills for the pine_ratio rule family (v1.5.10 restoration).

`_directional_exit_prices` realizes the OctaFx addendum line-17 intent on the
cycle-exit side: a LONG leg exits by SELLING -> bid (= raw - per-bar spread);
a SHORT leg exits by BUYING -> ask (raw, unchanged). spread=0 -> no-op (so the
pine_ratio exits are byte-identical to v1.2 on existing RESEARCH data).
"""
from __future__ import annotations

import pandas as pd

from tools.recycle_rules.pine_ratio_zrev_v1 import _directional_exit_prices


class _MockLeg:
    def __init__(self, symbol: str, direction: int, spread: float, ts: pd.Timestamp):
        self.symbol = symbol
        self.effective_direction = direction
        self.df = pd.DataFrame(
            {"open": [1.0], "close": [1.0], "spread": [spread]}, index=[ts]
        )


_TS = pd.Timestamp("2024-01-01", tz="UTC")


def test_long_leg_exit_fills_at_bid():
    legs = [_MockLeg("A", 1, 0.02, _TS)]  # long -> SELL -> bid
    out = _directional_exit_prices(legs, _TS, {"A": 1.5})
    assert abs(out["A"] - (1.5 - 0.02)) < 1e-12


def test_short_leg_exit_fills_at_ask():
    legs = [_MockLeg("B", -1, 0.02, _TS)]  # short -> BUY -> ask (unchanged)
    out = _directional_exit_prices(legs, _TS, {"B": 1.5})
    assert out["B"] == 1.5


def test_two_leg_cointegration_cycle():
    """A long+short basket: the long leg pays the exit spread, the short doesn't."""
    legs = [_MockLeg("LONG", 1, 0.03, _TS), _MockLeg("SHORT", -1, 0.03, _TS)]
    out = _directional_exit_prices(legs, _TS, {"LONG": 100.0, "SHORT": 50.0})
    assert abs(out["LONG"] - (100.0 - 0.03)) < 1e-12   # long exit = bid
    assert out["SHORT"] == 50.0                          # short exit = ask


def test_spread_zero_is_noop():
    legs = [_MockLeg("A", 1, 0.0, _TS), _MockLeg("B", -1, 0.0, _TS)]
    out = _directional_exit_prices(legs, _TS, {"A": 1.5, "B": 2.0})
    assert out == {"A": 1.5, "B": 2.0}


def test_missing_bar_falls_back_to_no_spread():
    """If the bar_ts isn't in the leg df, the lookup fails closed (spread=0)."""
    legs = [_MockLeg("A", 1, 0.05, _TS)]
    out = _directional_exit_prices(legs, pd.Timestamp("2099-01-01", tz="UTC"), {"A": 1.5})
    assert out["A"] == 1.5
