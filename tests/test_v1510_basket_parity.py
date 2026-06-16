"""Engine v1.5.10 — basket-compute parity vs frozen v1.5.9 (engine-level).

The basket pipeline (basket_runner) computes via `evaluate_bar`, dispatched by
`run_execution_loop`. This locks the central canonical claim for the basket
half: v1.5.10's basket compute is BYTE-IDENTICAL to frozen v1.5.9 at spread=0,
and correctly direction-aware (SELL@bid) at spread>0 while v1.5.9 stays
uncharged. Mirror of test_v1510_directional_fills (single-leg vs v1.5.8); here
the predecessor is v1.5.9 — the engine_abi.v1_5_9 basket compute.

run_execution_loop is the canonical driver of evaluate_bar, so comparing it
across v1_5_9 and v1_5_10 exercises the exact per-bar callable basket_runner
calls. Bypasses apply_regime_model via monkeypatch; synthetic df only, no
pipeline. (Full basket_runner end-to-end parity is added at the canonical flip,
when basket_runner re-points to engine_abi.v1_5_10.)
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

from engine_dev.universal_research_engine.v1_5_9 import execution_loop as e159
from engine_dev.universal_research_engine.v1_5_10 import execution_loop as e1510
from engines.filter_stack import FilterStack

SPREAD = 0.05  # price units, embedded in the RESEARCH `spread` column
FILL_BAR = 3   # signal at bar 2 -> fill at bar 3 open (next_bar_open)
EXIT_BAR = 6


def _df(n: int = 12, base: float = 100.0, atr: float = 5.0, spread: float = SPREAD) -> pd.DataFrame:
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
                "entry_reason": "basket_parity_test"}

    def check_exit(self, ctx):
        return getattr(ctx._ns, "index", None) == EXIT_BAR


@pytest.fixture
def _bypass(monkeypatch):
    monkeypatch.setattr(e159, "apply_regime_model", lambda df: df)
    monkeypatch.setattr(e1510, "apply_regime_model", lambda df: df)


def test_basket_spread_zero_byte_identical_to_v159(_bypass):
    """spread=0 -> v1.5.10 basket compute is bit-for-bit identical to frozen v1.5.9.

    This is the central canonical-promotion claim for the basket half."""
    for signal, mode in ((1, "long_only"), (-1, "short_only")):
        df = _df(spread=0.0)
        t9 = e159.run_execution_loop(df.copy(), _EntryExit(signal, mode))
        t10 = e1510.run_execution_loop(df.copy(), _EntryExit(signal, mode))
        assert len(t9) == len(t10) == 1
        assert set(t9[0].keys()) == set(t10[0].keys()), f"{mode}: key drift"
        for k in t9[0]:
            assert t9[0][k] == t10[0][k], f"{mode}: value mismatch at {k!r}"


def test_basket_short_entry_charges_at_bid_v1510_only(_bypass):
    """spread>0 -> v1.5.10 short entry (SELL) fills at bid; frozen v1.5.9 stays uncharged."""
    df = _df()
    t10 = e1510.run_execution_loop(df.copy(), _EntryExit(-1, "short_only"))[0]
    t9 = e159.run_execution_loop(df.copy(), _EntryExit(-1, "short_only"))[0]
    assert abs(t10["entry_price"] - (df.iloc[FILL_BAR]["open"] - SPREAD)) < 1e-12
    assert abs(t9["entry_price"] - df.iloc[FILL_BAR]["open"]) < 1e-12  # v1.5.9 = uncharged ask


def test_basket_round_trip_pays_one_spread(_bypass):
    """Flat round-trip on v1.5.10: P&L per unit == -spread, both directions."""
    for signal, mode in ((-1, "short_only"), (1, "long_only")):
        df = _df()
        t = e1510.run_execution_loop(df.copy(), _EntryExit(signal, mode))[0]
        pnl_per_unit = (t["exit_price"] - t["entry_price"]) * t["direction"]
        assert abs(pnl_per_unit - (-SPREAD)) < 1e-12, (
            f"{mode}: round-trip must pay exactly one spread, got {pnl_per_unit}")
