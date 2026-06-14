"""Engine v1.5.10 — direction-aware execution (engine-level unit tests).

Locks the RESTORATION of OctaFx addendum line-17 (ASK-for-BUY / BID-for-SELL):
SELL fills at the bid (= ask - per-bar RESEARCH `spread` column), BUY fills at
the ask. The P&L formula (exit-entry)*dir*units is UNCHANGED — only the fill
price fed into it becomes side-correct.

  (1) Short entry (SELL) fills at bid = open - spread.
  (2) Long  exit  (SELL) fills at bid = close - spread.
  (3) BUY-side fills (long entry, short exit) stay at the ask.
  (4) spread=0 -> trade dicts BYTE-IDENTICAL to frozen v1.5.8.
  (5) A flat round-trip pays exactly ONE spread, either direction
      (mirrors the GBPUSD PoC lock: short 0.91 -> 0.78).

Bypasses apply_regime_model via monkeypatch (synthetic df carries neutral
regime columns). No live data, no pipeline. Models tests/test_v157_engine_level.py.
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
from engine_dev.universal_research_engine.v1_5_10 import execution_loop as e1510
from engines.filter_stack import FilterStack

SPREAD = 0.05  # price units, embedded in the RESEARCH `spread` column
FILL_BAR = 3   # signal at bar 2 -> fill at bar 3 open (next_bar_open)
EXIT_BAR = 6


def _df(n: int = 12, base: float = 100.0, atr: float = 5.0, spread: float = SPREAD) -> pd.DataFrame:
    """Flat OHLC (no SL/TP hit) + a populated `spread` column + neutral regimes."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = np.full(n, base, dtype=float)
    return pd.DataFrame(
        {
            "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
            "atr": np.full(n, atr, dtype=float),
            "spread": np.full(n, spread, dtype=float),
            "volatility_regime": 0.0, "trend_regime": 0, "trend_label": "neutral",
            "trend_score": 0.0, "market_regime": "normal", "regime_age": 0,
            "regime_id": "NEUTRAL", "regime_age_exec": 0,
        },
        index=idx,
    )


def _sig(direction_mode: str) -> dict:
    return {
        "execution_rules": {
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 2.0},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
            "entry_when_flat_only": True, "pyramiding": False,
        },
        "trade_management": {"session_reset": "none"},
        "state_machine": {"entry": {"trigger": "signal_bar", "direction": direction_mode}},
    }


class _EntryExit:
    """Enter at bar 2 (fill at bar 3), exit via SIGNAL at bar 6."""

    def __init__(self, signal: int, direction_mode: str) -> None:
        self._signal = signal
        self.STRATEGY_SIGNATURE = _sig(direction_mode)
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        self._fired = False

    def prepare_indicators(self, df):
        return df

    def check_entry(self, ctx):
        if self._fired or getattr(ctx._ns, "index", None) != 2:
            return None
        self._fired = True
        return {"signal": self._signal,
                "entry_reference_price": float(ctx.require("close")),
                "entry_reason": "directional_test"}

    def check_exit(self, ctx):
        return getattr(ctx._ns, "index", None) == EXIT_BAR


@pytest.fixture
def _bypass(monkeypatch):
    monkeypatch.setattr(e1510, "apply_regime_model", lambda df: df)
    monkeypatch.setattr(e158, "apply_regime_model", lambda df: df)


def test_short_entry_fills_at_bid(_bypass):
    df = _df()
    t = e1510.run_execution_loop(df.copy(), _EntryExit(-1, "short_only"))[0]
    assert t["direction"] == -1
    # short ENTRY is a SELL -> bid = open - spread
    assert abs(t["entry_price"] - (df.iloc[FILL_BAR]["open"] - SPREAD)) < 1e-12
    # short EXIT is a BUY -> ask = close (unchanged)
    assert abs(t["exit_price"] - df.iloc[EXIT_BAR]["close"]) < 1e-12


def test_long_exit_fills_at_bid(_bypass):
    df = _df()
    t = e1510.run_execution_loop(df.copy(), _EntryExit(1, "long_only"))[0]
    assert t["direction"] == 1
    # long ENTRY is a BUY -> ask = open (unchanged)
    assert abs(t["entry_price"] - df.iloc[FILL_BAR]["open"]) < 1e-12
    # long EXIT is a SELL -> bid = close - spread
    assert abs(t["exit_price"] - (df.iloc[EXIT_BAR]["close"] - SPREAD)) < 1e-12


def test_round_trip_pays_exactly_one_spread(_bypass):
    """Flat price round-trip: P&L per unit == -spread, both directions.
    Mirrors the GBPUSD PoC lock (short 0.91 -> 0.78 = -one spread)."""
    for signal, mode in ((-1, "short_only"), (1, "long_only")):
        df = _df()
        t = e1510.run_execution_loop(df.copy(), _EntryExit(signal, mode))[0]
        pnl_per_unit = (t["exit_price"] - t["entry_price"]) * t["direction"]
        assert abs(pnl_per_unit - (-SPREAD)) < 1e-12, (
            f"{mode}: round-trip must pay exactly one spread, got {pnl_per_unit}")


def test_spread_zero_byte_identical_to_v158(_bypass):
    """spread=0 -> v1.5.10 output is bit-for-bit identical to frozen v1.5.8."""
    for signal, mode in ((1, "long_only"), (-1, "short_only")):
        df = _df(spread=0.0)
        t8 = e158.run_execution_loop(df.copy(), _EntryExit(signal, mode))
        t10 = e1510.run_execution_loop(df.copy(), _EntryExit(signal, mode))
        assert len(t8) == len(t10) == 1
        assert set(t8[0].keys()) == set(t10[0].keys()), f"{mode}: key drift"
        for k in t8[0]:
            assert t8[0][k] == t10[0][k], f"{mode}: value mismatch at {k!r}"
