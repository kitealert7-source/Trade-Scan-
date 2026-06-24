"""Engine Patch A (v1.5.11) step 4 — run-level engine_health counters.

Locks the two load-bearing properties:
  1. BYTE-IDENTITY — with health=None (the default), v1.5.11 trades are identical
     to v1.5.10's, and supplying a health dict never changes the trade list
     (the counters are observational only).
  2. POPULATION — each of the six counters tallies on a known-trigger scenario.

Design: outputs/system_reports/02_engine_core/ENGINE_PATCH_A_DESIGN_v1_5_11_2026-06-23.md §5/§8.4

Self-contained: synthesises a minimal strategy + OHLC frame and bypasses
apply_regime_model (the frame already carries neutral regime columns). No
production strategy, directive, or data is touched.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engines.filter_stack import FilterStack

V10 = importlib.import_module("engine_dev.universal_research_engine.v1_5_10.execution_loop")
V11 = importlib.import_module("engine_dev.universal_research_engine.v1_5_11.execution_loop")

_HEALTH_KEYS = {
    "rejected_entries", "stop_mutation_rejected", "pending_entries_expired",
    "force_close_count", "negative_spread_bars", "nan_bar_count",
}


# ---------------------------------------------------------------------------
# Minimal strategy + frame
# ---------------------------------------------------------------------------

class _Strat:
    """Fires one long signal at `fire_at`, returns no SL/TP (engine fallback)."""
    name = "health_test_strategy"

    def __init__(self, fire_at: int = 2, session_reset: str = "none",
                 stop_mutation=None) -> None:
        self.STRATEGY_SIGNATURE = {
            "execution_rules": {
                "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 1.5},
                "take_profit": {"type": "atr_multiple", "atr_multiplier": 3.0, "enabled": True},
                "entry_when_flat_only": True,
                "pyramiding": False,
            },
            "trade_management": {"session_reset": session_reset},
            "state_machine": {"entry": {"trigger": "signal_bar", "direction": "long_only"}},
        }
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        self._fire_at = fire_at
        self._fired = False
        self._stop_mutation = stop_mutation

    def prepare_indicators(self, df):
        return df

    def check_entry(self, ctx):
        if self._fired:
            return None
        if getattr(ctx._ns, "index", None) != self._fire_at:
            return None
        self._fired = True
        return {"signal": 1, "entry_reference_price": float(ctx.require("close")),
                "entry_reason": "fire"}

    def check_exit(self, ctx):
        return False

    # Only present when stop_mutation is configured (engine feature-detects it).
    def __getattr__(self, name):
        if name == "check_stop_mutation" and object.__getattribute__(self, "_stop_mutation") is not None:
            return object.__getattribute__(self, "_stop_mutation")
        raise AttributeError(name)


class _NoSignal(_Strat):
    def check_entry(self, ctx):
        return None


def _df(n: int = 60, base: float = 2000.0, atr: float = 5.0, drift: float = 0.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = base + drift * np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
            "atr": np.full(n, atr, dtype=float),
            "volatility_regime": 0.0, "trend_regime": 0, "trend_label": "neutral",
            "trend_score": 0.0, "market_regime": "normal",
        },
        index=idx,
    )


@pytest.fixture
def _no_regime(monkeypatch):
    monkeypatch.setattr(V10, "apply_regime_model", lambda d: d)
    monkeypatch.setattr(V11, "apply_regime_model", lambda d: d)


# ---------------------------------------------------------------------------
# 1. Byte-identity + observational invariance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("drift", [0.5, 0.0])  # TP-exit path + flat force-close path
def test_v11_health_none_byte_identical_to_v10(_no_regime, drift):
    t10 = V10.run_execution_loop(_df(drift=drift), _Strat())
    t11 = V11.run_execution_loop(_df(drift=drift), _Strat())
    assert t11 == t10
    assert len(t11) >= 1


def test_health_dict_does_not_change_trades(_no_regime):
    t_none = V11.run_execution_loop(_df(drift=0.5), _Strat())
    h: dict = {}
    t_health = V11.run_execution_loop(_df(drift=0.5), _Strat(), health=h)
    assert t_health == t_none
    assert set(h) >= _HEALTH_KEYS          # all six present
    assert all(isinstance(v, int) for v in h.values())


# ---------------------------------------------------------------------------
# 2. Each counter populates on a known trigger
# ---------------------------------------------------------------------------

def test_force_close_count(_no_regime):
    h: dict = {}
    trades = V11.run_execution_loop(_df(n=30, drift=0.0), _Strat(), health=h)  # flat -> held to EOD
    assert len(trades) == 1 and trades[0]["exit_source"] == "DATA_END"
    assert h["force_close_count"] == 1


def test_nan_and_negative_spread_probes(_no_regime):
    df = _df(n=30, drift=0.0)
    df.loc[df.index[5], "close"] = np.nan          # one NaN close
    df["spread"] = 0.0
    df.loc[df.index[7], "spread"] = -1.0           # two finite-negative spreads
    df.loc[df.index[8], "spread"] = -2.0
    h: dict = {}
    V11.run_execution_loop(df, _NoSignal(), health=h)
    assert h["nan_bar_count"] == 1
    assert h["negative_spread_bars"] == 2


def test_stop_mutation_rejected(_no_regime):
    # check_stop_mutation returns a stop far BELOW a long's current SL every bar
    # -> non-monotone -> rejected each held bar.
    strat = _Strat(stop_mutation=lambda ctx: 1.0)
    h: dict = {}
    V11.run_execution_loop(_df(n=20, drift=0.0), strat, health=h)
    assert h["stop_mutation_rejected"] >= 1


def test_rejected_entries(_no_regime):
    # A filter that vetoes the fired direction -> build returns None -> rejected.
    class _Veto:
        def allow_direction(self, d):
            return False
    strat = _Strat()
    strat.filter_stack = _Veto()
    h: dict = {}
    trades = V11.run_execution_loop(_df(n=20, drift=0.0), strat, health=h)
    assert trades == []
    assert h["rejected_entries"] == 1


def test_pending_entries_expired(_no_regime):
    # Fire on the last bar of UTC day 1 (23:00); the next bar rolls to day 2 and
    # session_reset='utc_day' discards the pending entry before it can fill.
    strat = _Strat(fire_at=23, session_reset="utc_day")
    h: dict = {}
    trades = V11.run_execution_loop(_df(n=26, drift=0.0), strat, health=h)
    assert trades == []
    assert h["pending_entries_expired"] == 1


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
