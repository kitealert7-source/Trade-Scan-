"""Canonical engine (v1.5.11) — direction-aware spread fills through the ENGINE
path (run_execution_loop -> evaluate_bar -> resolve_exit -> _exec_fill).

Answers "is the CANONICAL engine correct?" without comparing against any removed
predecessor. This is the behavioral coverage EXTRACTED from the retired v1.5.10
parity tests (test_v1510_directional_fills / _exit_fills_spread / _basket_parity)
during the engine consolidation (2026-06-30): those proved v1.5.10's fills by
byte-comparison vs the defective frozen v1.5.8/v1.5.9 engines, which are being
removed. The cross-engine byte-identity comparison retires with those engines
(git history is the forensic record); the absolute fill behavior it implicitly
asserted is kept here, re-anchored on the canonical engine.

Locks OctaFx addendum line-17 (ASK-for-BUY / BID-for-SELL) on v1.5.11:
  (1) short entry (SELL) fills at bid = open - spread; its BUY exit stays at ask.
  (2) long  entry (BUY) fills at ask = open; its SELL signal-exit fills at bid.
  (3) a flat round-trip pays EXACTLY one spread, either direction.
  (4) long STOP exit (SELL) fills at bid = stop level - spread  (R11: real SL fill).
  (5) long TP   exit (SELL) fills at bid = tp   level - spread  (R11: real TP fill).
The P&L formula (exit-entry)*dir*units is unchanged; only the side-correct fill
price feeding it is asserted. apply_regime_model is bypassed (synthetic df carries
neutral regime columns); no live data, no pipeline.
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

# Canonical engine ONLY — no predecessor import (the consolidation removed them).
from engine_dev.universal_research_engine.v1_5_11 import execution_loop as eng
from engines.filter_stack import FilterStack

SPREAD = 0.05          # price units, embedded in the RESEARCH `spread` column
BASE = 100.0
ATR = 5.0
STOP = BASE - 2 * ATR  # 90  (long stop = entry - stop_mult*ATR)
TP = BASE + 6 * ATR    # 130 (long tp   = entry + tp_mult*ATR)
FILL_BAR = 3           # signal bar 2 -> fill bar 3 open (next_bar_open)
SIGNAL_EXIT_BAR = 6
HIT_BAR = 4            # SL/TP trades through here (before any later signal exit)


def _df(n: int = 12, spread: float = SPREAD) -> pd.DataFrame:
    """Flat OHLC (no SL/TP hit) + a populated `spread` column + neutral regimes."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = np.full(n, BASE, dtype=float)
    return pd.DataFrame(
        {
            "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
            "atr": np.full(n, ATR, dtype=float),
            "spread": np.full(n, spread, dtype=float),
            "volatility_regime": 0.0, "trend_regime": 0, "trend_label": "neutral",
            "trend_score": 0.0, "market_regime": "normal", "regime_age": 0,
            "regime_id": "NEUTRAL", "regime_age_exec": 0,
        },
        index=idx,
    )


def _df_hit(kind: str, n: int = 9, spread: float = SPREAD) -> pd.DataFrame:
    """Flat at BASE except HIT_BAR, which trades through the stop or the TP."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    o = np.full(n, BASE); h = np.full(n, BASE); lo = np.full(n, BASE); c = np.full(n, BASE)
    if kind == "sl":
        h[HIT_BAR], lo[HIT_BAR], c[HIT_BAR] = BASE, STOP - 1.0, BASE - 5.0   # low 89 <= 90
    elif kind == "tp":
        h[HIT_BAR], lo[HIT_BAR], c[HIT_BAR] = TP + 1.0, BASE, TP             # high 131 >= 130
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
    """Enter at bar 2 (fill bar 3); exit via SIGNAL at SIGNAL_EXIT_BAR (no SL/TP)."""

    def __init__(self, signal: int, direction_mode: str, exit_bar: int = SIGNAL_EXIT_BAR) -> None:
        self._signal = signal
        self._exit_bar = exit_bar
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
        return getattr(ctx._ns, "index", None) == self._exit_bar


@pytest.fixture
def _bypass(monkeypatch):
    monkeypatch.setattr(eng, "apply_regime_model", lambda df: df)


def test_short_entry_fills_at_bid(_bypass):
    """Short entry (SELL) fills at bid = open - spread; its BUY exit stays at ask."""
    df = _df()
    t = eng.run_execution_loop(df.copy(), _EntryExit(-1, "short_only"))[0]
    assert t["direction"] == -1
    assert abs(t["entry_price"] - (df.iloc[FILL_BAR]["open"] - SPREAD)) < 1e-12
    assert abs(t["exit_price"] - df.iloc[SIGNAL_EXIT_BAR]["close"]) < 1e-12  # BUY exit = ask


def test_long_entry_and_signal_exit_fills(_bypass):
    """Long entry (BUY) fills at ask = open; long SIGNAL exit (SELL) fills at bid."""
    df = _df()
    t = eng.run_execution_loop(df.copy(), _EntryExit(1, "long_only"))[0]
    assert t["direction"] == 1
    assert abs(t["entry_price"] - df.iloc[FILL_BAR]["open"]) < 1e-12            # BUY entry = ask
    assert abs(t["exit_price"] - (df.iloc[SIGNAL_EXIT_BAR]["close"] - SPREAD)) < 1e-12  # SELL exit = bid


def test_round_trip_pays_exactly_one_spread(_bypass):
    """Flat price round-trip: P&L per unit == -spread, both directions."""
    for signal, mode in ((-1, "short_only"), (1, "long_only")):
        df = _df()
        t = eng.run_execution_loop(df.copy(), _EntryExit(signal, mode))[0]
        pnl_per_unit = (t["exit_price"] - t["entry_price"]) * t["direction"]
        assert abs(pnl_per_unit - (-SPREAD)) < 1e-12, (
            f"{mode}: round-trip must pay exactly one spread, got {pnl_per_unit}")


def test_long_sl_exit_fills_at_bid(_bypass):
    """Long STOP exit (SELL) fills at bid = stop level - spread; entry stays raw ask (R11)."""
    t = eng.run_execution_loop(_df_hit("sl"), _EntryExit(1, "long_only"))[0]
    assert t["exit_source"] == "STOP"
    assert abs(t["exit_price"] - (STOP - SPREAD)) < 1e-9, t["exit_price"]
    assert abs(t["entry_price"] - BASE) < 1e-9  # long entry = BUY@ask = raw open


def test_long_tp_exit_fills_at_bid(_bypass):
    """Long TP exit (SELL) fills at bid = tp level - spread (R11)."""
    t = eng.run_execution_loop(_df_hit("tp"), _EntryExit(1, "long_only"))[0]
    assert t["exit_source"] == "TP"
    assert abs(t["exit_price"] - (TP - SPREAD)) < 1e-9, t["exit_price"]
