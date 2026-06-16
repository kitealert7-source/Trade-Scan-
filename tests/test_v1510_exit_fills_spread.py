"""Engine v1.5.10 — spread>0 coverage through ACTUAL SL-hit and TP-hit exit fills.

test_v1510_directional_fills covers entry + a flat SIGNAL_EXIT round-trip; this
closes the R11 gap: drive spread>0 through a real STOP fill and a real TP fill
and assert the exit is side-correct (long exit = SELL = bid = level - spread),
for both the single-leg engine (v1.5.10 vs frozen v1.5.8) and the basket compute
(v1.5.10 vs frozen v1.5.9). Synthetic OHLC, apply_regime_model bypassed.

Setup: long entry at 100 (BUY@ask = raw open, no charge), ATR=5, stop 2xATR=90,
TP 6xATR=130. A bar then trades through the stop (low 89) or the TP (high 131);
resolve_exit fills at the level, _exec_fill charges the spread on the SELL exit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine_dev.universal_research_engine.v1_5_8 import execution_loop as e158
from engine_dev.universal_research_engine.v1_5_9 import execution_loop as e159
from engine_dev.universal_research_engine.v1_5_10 import execution_loop as e1510
from engines.filter_stack import FilterStack

SPREAD = 0.05
BASE = 100.0
ATR = 5.0
STOP = BASE - 2 * ATR   # 90  (long stop = entry - stop_mult*ATR)
TP = BASE + 6 * ATR     # 130 (long tp   = entry + tp_mult*ATR)
FILL_BAR = 3            # signal bar 2 -> fill bar 3 open
HIT_BAR = 4            # SL/TP trades through here (before the bar-6 signal exit)


def _df(kind: str, n: int = 9, spread: float = SPREAD) -> pd.DataFrame:
    """Flat at BASE except HIT_BAR, which trades through the stop or the TP."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    o = np.full(n, BASE); h = np.full(n, BASE); lo = np.full(n, BASE); c = np.full(n, BASE)
    if kind == "sl":
        h[HIT_BAR], lo[HIT_BAR], c[HIT_BAR] = BASE, STOP - 1.0, BASE - 5.0   # low 89 <= 90 <= high 100
    elif kind == "tp":
        h[HIT_BAR], lo[HIT_BAR], c[HIT_BAR] = TP + 1.0, BASE, TP             # high 131 >= 130 >= low 100
    return pd.DataFrame(
        {
            "open": o, "high": h, "low": lo, "close": c,
            "atr": np.full(n, ATR),
            "spread": np.full(n, spread),
            "volatility_regime": 0.0, "trend_regime": 0, "trend_label": "neutral",
            "trend_score": 0.0, "market_regime": "normal", "regime_age": 0,
            "regime_id": "NEUTRAL", "regime_age_exec": 0,
        },
        index=idx,
    )


def _sig() -> dict:
    return {
        "execution_rules": {
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 2.0},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
            "entry_when_flat_only": True, "pyramiding": False,
        },
        "trade_management": {"session_reset": "none"},
        "state_machine": {"entry": {"trigger": "signal_bar", "direction": "long_only"}},
    }


class _LongEntry:
    """Long entry at bar 2 (fill bar 3); no signal exit until bar 6 (SL/TP fires first)."""

    def __init__(self) -> None:
        self.STRATEGY_SIGNATURE = _sig()
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        self._fired = False

    def prepare_indicators(self, df):
        return df

    def check_entry(self, ctx):
        if self._fired or getattr(ctx._ns, "index", None) != 2:
            return None
        self._fired = True
        return {"signal": 1, "entry_reference_price": float(ctx.require("close")),
                "entry_reason": "exit_fill_test"}

    def check_exit(self, ctx):
        return getattr(ctx._ns, "index", None) == 6


@pytest.fixture
def _bypass(monkeypatch):
    for m in (e158, e159, e1510):
        monkeypatch.setattr(m, "apply_regime_model", lambda df: df)


def test_long_sl_exit_fills_at_bid_v1510(_bypass):
    """Long STOP exit is a SELL -> fills at bid = stop level - spread."""
    t = e1510.run_execution_loop(_df("sl"), _LongEntry())[0]
    assert t["exit_source"] == "STOP"
    assert abs(t["exit_price"] - (STOP - SPREAD)) < 1e-9, t["exit_price"]
    assert abs(t["entry_price"] - BASE) < 1e-9  # long entry = BUY@ask = raw open


def test_long_tp_exit_fills_at_bid_v1510(_bypass):
    """Long TP exit is a SELL -> fills at bid = tp level - spread."""
    t = e1510.run_execution_loop(_df("tp"), _LongEntry())[0]
    assert t["exit_source"] == "TP"
    assert abs(t["exit_price"] - (TP - SPREAD)) < 1e-9, t["exit_price"]


@pytest.mark.parametrize("kind", ["sl", "tp"])
def test_exit_fills_spread_zero_byte_identical_to_v158(_bypass, kind):
    """spread=0 -> SL/TP exit fills are bit-identical to frozen v1.5.8 (single-leg)."""
    t8 = e158.run_execution_loop(_df(kind, spread=0.0), _LongEntry())
    t10 = e1510.run_execution_loop(_df(kind, spread=0.0), _LongEntry())
    assert len(t8) == len(t10) == 1
    assert set(t8[0]) == set(t10[0])
    for k in t8[0]:
        assert t8[0][k] == t10[0][k], f"{kind}: mismatch at {k!r}"


@pytest.mark.parametrize("kind,level", [("sl", STOP), ("tp", TP)])
def test_basket_exit_charges_v1510_vs_v159(_bypass, kind, level):
    """Basket compute: v1.5.10 SL/TP long exit fills at level-spread; frozen v1.5.9 at level."""
    t10 = e1510.run_execution_loop(_df(kind), _LongEntry())[0]
    t9 = e159.run_execution_loop(_df(kind), _LongEntry())[0]
    assert abs(t10["exit_price"] - (level - SPREAD)) < 1e-9, t10["exit_price"]
    assert abs(t9["exit_price"] - level) < 1e-9, t9["exit_price"]  # v1.5.9 uncharged
