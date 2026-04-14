"""Regression: engine SL/TP fallback must use directive multipliers.

Why this test exists
--------------------
`engine_dev/universal_research_engine/v1_5_4/execution_loop.py` provides an
ATR-based fallback for `stop_price` and `tp_price` when a strategy's
`check_entry` omits them (the STOP-CONTRACT-safe pattern enforced by
`governance/stop_contract_checker.py`).

Historical bite
---------------
The fallback used to hardcode `ENGINE_ATR_MULTIPLIER = 2.0` for SL and had
**no TP fallback at all**. Every strategy that had its `stop_price`/
`tp_price` stripped by the stop-contract patch silently switched to 2.0x
ATR stops with no take-profit, inflating SL width and producing multi-year
buy-and-hold artifacts (46_STR_XAU_1H_CHOCH_S01_V2_P01 2024-02-14 entry
held to 2026-03-20 EOD).

Lock-in
-------
This test instantiates a minimal strategy that returns a signal without
stop_price/tp_price, declares SL=1.5*ATR and TP=3.0*ATR in its signature,
and asserts that the single emitted trade's `risk_distance` == 1.5*ATR
(within float tolerance) and its TP price is at 3.0*ATR from fill.
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

from engine_dev.universal_research_engine.v1_5_4 import execution_loop as eloop
from engines.filter_stack import FilterStack


class _FallbackStrategy:
    """Minimal strategy — fires one long signal at bar 2, returns no SL/TP."""

    name = "test_fallback_strategy"

    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 1.5},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 3.0, "enabled": True},
            "entry_when_flat_only": True,
            "pyramiding": False,
        },
        "trade_management": {"session_reset": "none"},
        "state_machine": {"entry": {"trigger": "signal_bar", "direction": "long_only"}},
    }

    def __init__(self) -> None:
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        self._fired = False

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx):
        # Fire exactly once, early in the series. No stop_price / tp_price.
        if self._fired:
            return None
        i = getattr(ctx._ns, "index", None)
        if i != 2:
            return None
        self._fired = True
        return {
            "signal": 1,
            "entry_reference_price": float(ctx.require("close")),
            "entry_reason": "test_fire",
        }

    def check_exit(self, ctx):
        return False


def _synthetic_df(n: int = 60, base: float = 2000.0, atr: float = 5.0,
                  drift: float = 0.0) -> pd.DataFrame:
    """Linear-drift OHLC with constant ATR.

    drift > 0 → price rises, eventually crossing a long TP ≈ entry + 3*ATR.
    drift = 0 → flat; trade held to end-of-series (force-close path)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = base + drift * np.arange(n, dtype=float)
    df = pd.DataFrame(
        {
            "open":  close,
            "high":  close + 0.1,
            "low":   close - 0.1,
            "close": close,
            "atr":   np.full(n, atr, dtype=float),
            # Regime columns required by FilterStack / ctx.require — neutral values.
            "volatility_regime": 0.0,
            "trend_regime":      0,
            "trend_label":       "neutral",
            "trend_score":       0.0,
            "market_regime":     "normal",
        },
        index=idx,
    )
    return df


@pytest.fixture
def _no_regime_override(monkeypatch):
    """Bypass apply_regime_model — the synthetic df already carries neutral regime cols."""
    monkeypatch.setattr(eloop, "apply_regime_model", lambda df: df)


def test_engine_fallback_respects_directive_atr_multipliers(_no_regime_override):
    """When strategy omits stop_price/tp_price, engine fallback must compute
    SL and TP using the multipliers declared in
    execution_rules.stop_loss.atr_multiplier / take_profit.atr_multiplier."""
    atr_val = 5.0
    base    = 2000.0
    # Rising drift so the fallback-computed TP (entry + 3*ATR = entry + 15)
    # is actually reached within the series and we can inspect exit_source.
    df      = _synthetic_df(n=60, base=base, atr=atr_val, drift=0.5)
    strat   = _FallbackStrategy()

    trades = eloop.run_execution_loop(df, strat)

    assert len(trades) == 1, f"expected exactly one trade, got {len(trades)}"
    t = trades[0]

    # SL: risk_distance must equal 1.5 * ATR (directive multiplier), not 2.0 (legacy default).
    expected_sl = 1.5 * atr_val
    assert abs(t["risk_distance"] - expected_sl) < 1e-6, (
        f"SL regression: risk_distance={t['risk_distance']} "
        f"expected {expected_sl} (1.5 * ATR). Engine likely reverted to "
        f"hardcoded ENGINE_ATR_MULTIPLIER."
    )

    # stop_source must be ENGINE_FALLBACK (strategy did not return stop_price).
    assert t["stop_source"] == "ENGINE_FALLBACK", (
        f"expected stop_source=ENGINE_FALLBACK, got {t['stop_source']!r}"
    )

    # TP: engine must have synthesized a tp_price from the directive's 3.0 ATR
    # multiplier, and resolve_exit must have fired it. If TP fallback is not
    # wired, the trade instead falls through to the end-of-series force-close
    # (exit_source=None) at the last bar's close.
    assert t["exit_source"] == "TP", (
        f"TP fallback missing: expected exit_source='TP' when price crosses "
        f"entry + 3*ATR, got {t['exit_source']!r}. Engine did not synthesize "
        f"tp_price from execution_rules.take_profit.atr_multiplier."
    )
    expected_tp_distance = 3.0 * atr_val
    actual_tp_distance   = t["exit_price"] - t["entry_price"]
    assert abs(actual_tp_distance - expected_tp_distance) < 1e-6, (
        f"TP regression: tp_distance={actual_tp_distance} "
        f"expected {expected_tp_distance} (3.0 * ATR)."
    )


def test_engine_fallback_defaults_when_signature_silent(_no_regime_override):
    """Safety net: if the signature declares NO atr_multiplier, the engine
    must fall back to ENGINE_ATR_MULTIPLIER (legacy default) and produce no
    TP. This locks the documented precedence order."""

    class _SilentStrategy(_FallbackStrategy):
        STRATEGY_SIGNATURE = {
            "execution_rules": {
                "stop_loss":   {"type": "atr_multiple"},   # no atr_multiplier
                "take_profit": {"enabled": False},
                "entry_when_flat_only": True,
            },
            "trade_management": {"session_reset": "none"},
            "state_machine": {"entry": {"trigger": "signal_bar", "direction": "long_only"}},
        }

    atr_val = 4.0
    # Flat drift → no TP can fire; SL at 2.0*ATR won't trigger either; trade
    # closes via the engine's end-of-series force-close path.
    df      = _synthetic_df(n=30, base=1000.0, atr=atr_val, drift=0.0)
    trades  = eloop.run_execution_loop(df, _SilentStrategy())

    assert len(trades) == 1
    t = trades[0]
    expected_sl = eloop.ENGINE_ATR_MULTIPLIER * atr_val
    assert abs(t["risk_distance"] - expected_sl) < 1e-6, (
        f"when signature omits SL atr_multiplier, engine must fall back to "
        f"ENGINE_ATR_MULTIPLIER ({eloop.ENGINE_ATR_MULTIPLIER}); got "
        f"risk_distance={t['risk_distance']}"
    )
    # With take_profit.enabled=False, no TP must have been synthesized; the
    # trade must NOT exit via TP.
    assert t["exit_source"] != "TP", (
        f"expected no TP exit when take_profit disabled; got exit_source={t['exit_source']!r}"
    )


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
