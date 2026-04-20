"""Engine v1.5.7 — engine-level invariants (synthetic-data unit tests).

Locks the four contractual guarantees of the v1.5.7 EXPERIMENTAL successor
to v1.5.6 FROZEN:

  (1) Byte-equivalence: a strategy with NO partial/stop-mutation hooks must
      produce trade dicts whose keys + values match v1.5.6 output bit-for-bit
      on the same synthetic input. No new keys may leak into no-hook output.

  (2) Partial-exit trigger:   fires at unrealized_r >= 1.0001 (epsilon).

  (3) Entry-bar guard:        partial hook is NOT consulted on entry bar
      (bars_held == 0) even if unrealized_r >= 1.0001.

  (4) No-double-partial:      partial fires AT MOST ONCE per trade;
      strategy.check_partial_exit is not invoked after partial_taken.

These tests bypass `apply_regime_model` via monkeypatch — the synthetic df
carries neutral regime columns — and exercise `run_execution_loop` directly.
No live data, no tools/, no pipeline.
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

from engine_dev.universal_research_engine.v1_5_6 import execution_loop as eloop_v156
from engine_dev.universal_research_engine.v1_5_7 import execution_loop as eloop_v157
from engines.filter_stack import FilterStack


# -----------------------------------------------------------------------------
# Shared synthetic data
# -----------------------------------------------------------------------------

def _synthetic_df(n: int = 80, base: float = 2000.0, atr: float = 5.0,
                  drift: float = 0.0) -> pd.DataFrame:
    """Linear-drift OHLC with constant ATR + neutral regime columns.

    drift > 0 rises (long wins).  Long entry at bar 2 with 2.0*ATR
    SL and 6.0*ATR TP gives: 1R = 2*ATR = 10.0 price units. drift=0.5 per bar
    reaches +1R after ~20 bars from fill — well inside a 60-bar window.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = base + drift * np.arange(n, dtype=float)
    df = pd.DataFrame(
        {
            "open":  close,
            "high":  close + 0.1,
            "low":   close - 0.1,
            "close": close,
            "atr":   np.full(n, atr, dtype=float),
            # Neutral regime columns (engine uses ctx.require or row.get; both succeed)
            "volatility_regime": 0.0,
            "trend_regime":      0,
            "trend_label":       "neutral",
            "trend_score":       0.0,
            "market_regime":     "normal",
            "regime_age":        0,
            "regime_id":         "NEUTRAL",
            "regime_age_exec":   0,
        },
        index=idx,
    )
    return df


# -----------------------------------------------------------------------------
# Strategy fixtures
# -----------------------------------------------------------------------------

_BASE_SIGNATURE = {
    "execution_rules": {
        "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 2.0},
        "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
        "entry_when_flat_only": True,
        "pyramiding": False,
    },
    "trade_management": {"session_reset": "none"},
    "state_machine": {"entry": {"trigger": "signal_bar", "direction": "long_only"}},
}


class _NoHookStrategy:
    """No check_partial_exit, no check_stop_mutation — pure v1.5.6 behavior."""
    name = "no_hook_strategy"
    STRATEGY_SIGNATURE = _BASE_SIGNATURE

    def __init__(self) -> None:
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        self._fired = False

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx):
        if self._fired:
            return None
        i = getattr(ctx._ns, "index", None)
        if i != 2:
            return None
        self._fired = True
        return {"signal": 1, "entry_reference_price": float(ctx.require("close")),
                "entry_reason": "test_fire"}

    def check_exit(self, ctx):
        return False


class _PartialAt1R(_NoHookStrategy):
    """Fires partial 50% whenever engine guards admit (i.e. bars_held>=1 and UR>=1.0001)."""
    name = "partial_at_1r"

    def __init__(self) -> None:
        super().__init__()
        self.partial_calls = 0
        self.partial_call_urs: list[float | None] = []

    def check_partial_exit(self, ctx):
        # If engine is calling us, guards already pass — but record UR for audit.
        self.partial_calls += 1
        ur = getattr(ctx._ns, "unrealized_r", None)
        self.partial_call_urs.append(ur)
        return {"fraction": 0.5, "reason": "partial_at_1r"}


class _EagerPartial(_NoHookStrategy):
    """Returns a partial signal EVERY bar it's called. Validates engine-side
    no-double-partial guard: engine must stop calling us after partial_taken."""
    name = "eager_partial"

    def __init__(self) -> None:
        super().__init__()
        self.partial_calls = 0

    def check_partial_exit(self, ctx):
        self.partial_calls += 1
        return {"fraction": 0.5, "reason": "eager"}


class _EntryBarPartialSpy(_NoHookStrategy):
    """Returns a partial signal every call. If the engine called us on the
    entry bar (bars_held == 0) the spy would record it — which must NEVER
    happen per the bars_held >= 1 guard."""
    name = "entry_bar_spy"

    def __init__(self) -> None:
        super().__init__()
        self.bars_held_at_calls: list[int] = []

    def check_partial_exit(self, ctx):
        self.bars_held_at_calls.append(int(getattr(ctx._ns, "bars_held", -1)))
        return {"fraction": 0.5, "reason": "spy"}


class _PartialAtOneR_NoExit(_NoHookStrategy):
    """50% partial at >=1R. No time/signal exit — lets SL or TP close the
    remainder. Fires the entry at bar 3 (signal at bar 2, fill at bar 3)."""
    name = "partial_only_1r_50pct"

    def __init__(self) -> None:
        super().__init__()
        self._fired = False

    def check_entry(self, ctx):
        if self._fired:
            return None
        i = getattr(ctx._ns, "index", None)
        if i != 2:
            return None
        self._fired = True
        return {"signal": 1, "entry_reference_price": float(ctx.require("close")),
                "entry_reason": "partial_only_fire"}

    def check_partial_exit(self, ctx):
        return {"fraction": 0.5, "reason": "p50_at_1r"}


class _PartialPlusBE(_PartialAtOneR_NoExit):
    """50% partial + move SL to breakeven (entry price) once UR>=1R.
    Also records ctx.unrealized_r on every bar via check_exit for
    initial-stop-invariance auditing."""
    name = "partial_plus_be"

    def __init__(self) -> None:
        super().__init__()
        self._be_done = False
        self.ur_audit: list[tuple[int, int, float | None]] = []  # (bar_idx, bars_held, ur)

    def check_stop_mutation(self, ctx):
        if self._be_done:
            return None
        ur = getattr(ctx._ns, "unrealized_r", None)
        if ur is None or ur < 1.0001:
            return None
        bars_held = int(getattr(ctx._ns, "bars_held", 0))
        if bars_held < 1:
            return None
        # Move SL to entry price (BE). We need the entry price — infer from
        # ctx.row['close'] minus (ur * risk). Simpler: track locally.
        self._be_done = True
        return self._entry_price  # set by check_entry below

    def check_entry(self, ctx):
        sig = super().check_entry(ctx)
        if sig is not None:
            # Record entry reference so check_stop_mutation can return it as BE.
            self._entry_price = float(ctx.require("close"))
        return sig

    def check_exit(self, ctx):
        # Audit channel — records UR every bar (post-partial, post-mutation
        # in canonical order). Engine computes ctx.unrealized_r once per bar
        # using initial_stop_price, so this value is what partial + stop_mut
        # hooks saw on the same bar.
        ns = ctx._ns
        self.ur_audit.append((
            int(getattr(ns, "index", -1)),
            int(getattr(ns, "bars_held", -1)),
            getattr(ns, "unrealized_r", None),
        ))
        return False


def _custom_ohlc_df(opens, highs, lows, closes, atr_val: float) -> pd.DataFrame:
    """Build a df with explicit OHLC arrays + neutral regime columns + ATR."""
    n = len(closes)
    assert n == len(opens) == len(highs) == len(lows)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open":  np.asarray(opens,  dtype=float),
            "high":  np.asarray(highs,  dtype=float),
            "low":   np.asarray(lows,   dtype=float),
            "close": np.asarray(closes, dtype=float),
            "atr":   np.full(n, atr_val, dtype=float),
            "volatility_regime": 0.0,
            "trend_regime":      0,
            "trend_label":       "neutral",
            "trend_score":       0.0,
            "market_regime":     "normal",
            "regime_age":        0,
            "regime_id":         "NEUTRAL",
            "regime_age_exec":   0,
        },
        index=idx,
    )


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def _bypass_regime_both(monkeypatch):
    """Bypass apply_regime_model on BOTH v1.5.6 and v1.5.7 engines — the
    synthetic df already carries neutral regime columns."""
    monkeypatch.setattr(eloop_v156, "apply_regime_model", lambda df: df)
    monkeypatch.setattr(eloop_v157, "apply_regime_model", lambda df: df)


# -----------------------------------------------------------------------------
# Test 1 — no-hook byte-equivalence vs v1.5.6
# -----------------------------------------------------------------------------

def test_v157_no_hook_byte_equivalent_to_v156(_bypass_regime_both):
    """A strategy without partial/stop-mutation hooks must emit trade dicts
    on v1.5.7 that compare equal to the v1.5.6 output on the same input.

    Rationale: v1.5.7 must not regress pre-existing strategies. The new
    fields (partial_leg / partial_of_parent / stop_mutation_rejected) must
    be ABSENT from the dict — not set to None/False — so downstream tooling
    that iterates dict.items() sees no schema drift."""
    df = _synthetic_df(n=80, drift=0.0)   # flat => no TP hit => force-close path

    strat_a = _NoHookStrategy()
    strat_b = _NoHookStrategy()

    trades_v156 = eloop_v156.run_execution_loop(df.copy(), strat_a)
    trades_v157 = eloop_v157.run_execution_loop(df.copy(), strat_b)

    assert len(trades_v156) == len(trades_v157) == 1

    t6 = trades_v156[0]
    t7 = trades_v157[0]

    # Strict key-set equality — v1.5.7 must add ZERO keys when no hooks.
    assert set(t6.keys()) == set(t7.keys()), (
        f"v1.5.7 schema drift for no-hook strategy.\n"
        f"  v1.5.6 only: {set(t6) - set(t7)}\n"
        f"  v1.5.7 only: {set(t7) - set(t6)}"
    )
    # Per-key value equality.
    for k in t6:
        assert t6[k] == t7[k], f"value mismatch at key {k!r}: v156={t6[k]!r} v157={t7[k]!r}"

    # Sanity: the forbidden v1.5.7 additions are truly absent.
    for forbidden in ("partial_leg", "partial_of_parent", "stop_mutation_rejected"):
        assert forbidden not in t7, f"v1.5.7 leaked {forbidden!r} into no-hook trade dict"


# -----------------------------------------------------------------------------
# Test 2 — partial fires at UR >= 1.0001
# -----------------------------------------------------------------------------

def test_v157_partial_fires_when_unrealized_r_crosses_threshold(_bypass_regime_both):
    """With 2.0*ATR SL and drift 0.5 per bar, 1R = 2*ATR = 10.0 price units
    above entry. Entry at bar 2 open ~2001.0; 1R target = 2011.0. Close
    crosses this around bar 22. Partial must fire on (or just after) that
    bar, with UR just above 1.0 — never below 1.0001."""
    df    = _synthetic_df(n=80, drift=0.5)
    strat = _PartialAt1R()

    trades = eloop_v157.run_execution_loop(df.copy(), strat)

    assert len(trades) == 1, f"expected 1 trade, got {len(trades)}"
    t = trades[0]

    # Partial must have fired — trade dict carries partial_leg.
    assert "partial_leg" in t, "partial_leg missing from trade dict"
    assert t.get("partial_of_parent") is True

    leg = t["partial_leg"]
    assert 0.01 <= leg["fraction"] <= 0.99
    assert leg["fraction"] == 0.5
    assert leg["unrealized_r"] >= 1.0001, (
        f"partial fired below epsilon threshold: UR={leg['unrealized_r']} "
        f"(engine must enforce UR >= 1.0001)"
    )
    # And every recorded call from the strategy must have seen UR >= 1.0001.
    for ur in strat.partial_call_urs:
        assert ur is not None and ur >= 1.0001, (
            f"strategy.check_partial_exit was called with UR={ur} (< 1.0001) — "
            f"engine guard failed"
        )

    # Strategy was called at least once (partial fired), exactly once (no double call).
    assert strat.partial_calls >= 1


# -----------------------------------------------------------------------------
# Test 3 — entry-bar guard (bars_held >= 1)
# -----------------------------------------------------------------------------

def test_v157_partial_hook_not_called_on_entry_bar(_bypass_regime_both):
    """On the fill bar itself (bars_held == 0) the engine MUST NOT consult
    check_partial_exit, even if UR >= 1.0001 by that bar's close. This test
    would catch a regression where the guard is relaxed to bars_held >= 0."""
    df    = _synthetic_df(n=80, drift=0.5)
    strat = _EntryBarPartialSpy()

    _ = eloop_v157.run_execution_loop(df.copy(), strat)

    for bh in strat.bars_held_at_calls:
        assert bh >= 1, (
            f"check_partial_exit was called on entry bar (bars_held={bh}); "
            f"engine guard _PARTIAL_MIN_BARS_HELD=1 regressed"
        )


# -----------------------------------------------------------------------------
# Test 4 — no-double-partial
# -----------------------------------------------------------------------------

def test_v157_partial_fires_at_most_once_per_trade(_bypass_regime_both):
    """Even though _EagerPartial returns a partial signal on every call,
    the engine must call check_partial_exit AT MOST ONCE per trade — the
    `partial_taken` latch is engine-side, not strategy-side."""
    df    = _synthetic_df(n=80, drift=0.5)
    strat = _EagerPartial()

    trades = eloop_v157.run_execution_loop(df.copy(), strat)

    assert len(trades) == 1
    t = trades[0]

    # Hook was invoked exactly once across the entire trade.
    assert strat.partial_calls == 1, (
        f"check_partial_exit called {strat.partial_calls}x — engine must "
        f"short-circuit on partial_taken after first fire"
    )
    # That one call produced a partial_leg on the trade.
    assert "partial_leg" in t


# -----------------------------------------------------------------------------
# Test 5 — PnL conservation (partial @ +1R, TP @ +6R)
# -----------------------------------------------------------------------------

_CONSERVATION_TOL = 1e-9   # tighter than tick — R is a pure ratio, no fills jitter

def _composite_r_from_trade(t: dict, frac: float) -> float:
    """Reconstruct composite R-multiple for a partial + remainder trade."""
    risk = t["risk_distance"]
    remainder_r = (t["exit_price"] - t["entry_price"]) / risk
    if t["direction"] == -1:
        remainder_r = -remainder_r
    partial_r = t["partial_leg"]["unrealized_r"]
    return frac * partial_r + (1.0 - frac) * remainder_r


def test_v157_pnl_conservation_partial_then_tp(_bypass_regime_both):
    """Partial @ +1R then TP @ +6R must sum (weighted by fraction) to the
    analytical two-trade split — to numerical precision."""
    atr = 2.0
    closes = [100.0, 100.0, 100.0, 100.0, 102.2, 108.0, 112.0]
    opens  = closes[:]
    highs  = closes[:]
    lows   = closes[:]
    highs[-1] = 112.0
    lows[-1]  = 110.0

    df = _custom_ohlc_df(opens, highs, lows, closes, atr_val=atr)

    strat = _PartialAtOneR_NoExit()
    strat.STRATEGY_SIGNATURE = {
        **_BASE_SIGNATURE,
        "execution_rules": {
            **_BASE_SIGNATURE["execution_rules"],
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 1.0},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
        },
    }
    strat.filter_stack = FilterStack(strat.STRATEGY_SIGNATURE)

    trades = eloop_v157.run_execution_loop(df.copy(), strat)

    assert len(trades) == 1
    t = trades[0]

    assert t["exit_source"] == "TP", f"expected TP, got {t['exit_source']!r}"
    assert t["entry_price"] == 100.0
    assert t["risk_distance"] == 2.0
    assert t["initial_stop_price"] == 98.0
    assert t["exit_price"] == 112.0, f"TP fill mismatch: {t['exit_price']}"
    assert "partial_leg" in t
    leg = t["partial_leg"]
    assert leg["fraction"] == 0.5

    partial_r  = (102.2 - 100.0) / 2.0         # 1.10
    remainder_r = (112.0 - 100.0) / 2.0        # 6.00
    expected_composite = 0.5 * partial_r + 0.5 * remainder_r   # 3.55

    engine_composite = _composite_r_from_trade(t, leg["fraction"])

    assert abs(engine_composite - expected_composite) < _CONSERVATION_TOL, (
        f"PnL conservation broken:\n"
        f"  analytical (synthetic split): {expected_composite:.12f}R\n"
        f"  engine reconstruction:         {engine_composite:.12f}R\n"
        f"  delta:                         {engine_composite - expected_composite:+.3e}R\n"
        f"  partial UR: {leg['unrealized_r']}, remainder fill: {t['exit_price']}"
    )

    assert abs(leg["unrealized_r"] - partial_r) < _CONSERVATION_TOL


# -----------------------------------------------------------------------------
# Test 6 — path independence (partial @ +1R then reverse to SL)
# -----------------------------------------------------------------------------

def test_v157_path_independence_partial_then_sl(_bypass_regime_both):
    """After partial exit, remainder's SL must fill at the ORIGINAL SL —
    not a BE-shifted stop (we use NO stop mutation hook), and position
    sizing must be untouched."""
    atr = 2.0
    closes = [100.0, 100.0, 100.0, 100.0, 102.2, 99.0, 97.0]
    opens  = closes[:]
    highs  = closes[:]
    lows   = closes[:]
    highs[-1] = 99.0
    lows[-1]  = 97.0
    opens[-1] = 99.0

    df = _custom_ohlc_df(opens, highs, lows, closes, atr_val=atr)

    strat = _PartialAtOneR_NoExit()
    strat.STRATEGY_SIGNATURE = {
        **_BASE_SIGNATURE,
        "execution_rules": {
            **_BASE_SIGNATURE["execution_rules"],
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 1.0},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
        },
    }
    strat.filter_stack = FilterStack(strat.STRATEGY_SIGNATURE)

    trades = eloop_v157.run_execution_loop(df.copy(), strat)

    assert len(trades) == 1
    t = trades[0]

    assert t["exit_source"] == "STOP", f"expected STOP, got {t['exit_source']!r}"
    assert t["exit_price"] == 98.0, (
        f"SL fill drift — expected 98.0 (original SL), got {t['exit_price']}. "
        f"Possible bug: stop_price_active was mutated or partial shifted SL."
    )
    assert t["initial_stop_price"] == 98.0
    assert t["risk_distance"] == 2.0
    assert "partial_leg" in t
    leg = t["partial_leg"]
    assert leg["fraction"] == 0.5

    partial_r  = (102.2 - 100.0) / 2.0         # 1.10
    remainder_r = (98.0 - 100.0) / 2.0         # -1.00
    expected_composite = 0.5 * partial_r + 0.5 * remainder_r   # +0.05

    engine_composite = _composite_r_from_trade(t, leg["fraction"])

    assert abs(engine_composite - expected_composite) < _CONSERVATION_TOL, (
        f"Path-independence conservation broken:\n"
        f"  analytical: {expected_composite:.12f}R\n"
        f"  engine:     {engine_composite:.12f}R\n"
        f"  delta:      {engine_composite - expected_composite:+.3e}R"
    )


# -----------------------------------------------------------------------------
# Test 7 — trade log integrity invariants
# -----------------------------------------------------------------------------

def test_v157_trade_log_integrity_invariants(_bypass_regime_both):
    """Applied to Test 5 scenario — partial + TP."""
    atr = 2.0
    closes = [100.0, 100.0, 100.0, 100.0, 102.2, 108.0, 112.0]
    opens, highs, lows = closes[:], closes[:], closes[:]
    highs[-1] = 112.0
    lows[-1]  = 110.0

    df = _custom_ohlc_df(opens, highs, lows, closes, atr_val=atr)

    strat = _PartialAtOneR_NoExit()
    strat.STRATEGY_SIGNATURE = {
        **_BASE_SIGNATURE,
        "execution_rules": {
            **_BASE_SIGNATURE["execution_rules"],
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 1.0},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
        },
    }
    strat.filter_stack = FilterStack(strat.STRATEGY_SIGNATURE)

    trades = eloop_v157.run_execution_loop(df.copy(), strat)
    assert len(trades) == 1
    t = trades[0]
    leg = t["partial_leg"]

    # (a) strict temporal ordering
    assert leg["exit_index"] < t["exit_index"]
    # (b) MFE monotone
    assert leg["trade_high"] <= t["trade_high"]
    # (c) MAE monotone
    assert leg["trade_low"] >= t["trade_low"]
    # (d) bars_held non-decreasing
    assert leg["bars_held"] <= t["bars_held"]
    # (e) direction preserved
    assert t["direction"] == 1
    # (f) initial stop / risk distance unchanged
    assert t["initial_stop_price"] == 98.0
    assert t["risk_distance"] == 2.0


# -----------------------------------------------------------------------------
# Test 8 — unrealized_r always uses INITIAL stop distance (even after BE)
# -----------------------------------------------------------------------------

def test_v157_unrealized_r_uses_initial_stop_after_be_mutation(_bypass_regime_both):
    atr = 2.0
    closes = [100.0, 100.0, 100.0, 100.0, 102.2, 104.0, 106.3, 100.0]
    opens, highs, lows = closes[:], closes[:], closes[:]
    highs[-1] = 101.0
    lows[-1]  = 100.0
    opens[-1] = 101.0

    df = _custom_ohlc_df(opens, highs, lows, closes, atr_val=atr)

    strat = _PartialPlusBE()
    strat.STRATEGY_SIGNATURE = {
        **_BASE_SIGNATURE,
        "execution_rules": {
            **_BASE_SIGNATURE["execution_rules"],
            "stop_loss":   {"type": "atr_multiple", "atr_multiplier": 1.0},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 6.0, "enabled": True},
        },
    }
    strat.filter_stack = FilterStack(strat.STRATEGY_SIGNATURE)

    trades = eloop_v157.run_execution_loop(df.copy(), strat)
    assert len(trades) == 1
    t = trades[0]

    # (1) Remainder exited at BE-mutated stop = 100.0 (NOT at original 98).
    assert t["exit_source"] == "STOP"
    assert t["exit_price"] == 100.0, (
        f"BE stop mutation did not take effect — exit at {t['exit_price']} "
        f"(expected 100.0)"
    )

    # (2) initial_stop_price in trade dict is FROZEN at original 98.0.
    assert t["initial_stop_price"] == 98.0, (
        f"initial_stop_price was overwritten by mutation: got "
        f"{t['initial_stop_price']} (expected 98.0)"
    )
    assert t["risk_distance"] == 2.0

    # (3) ctx.unrealized_r at every post-entry bar uses ORIGINAL risk denominator.
    entry_price = 100.0
    initial_risk = 2.0
    for bar_idx, bars_held, ur in strat.ur_audit:
        if bars_held <= 0 or ur is None:
            continue
        close = df.iloc[bar_idx]["close"]
        expected_ur = (close - entry_price) / initial_risk
        assert abs(ur - expected_ur) < 1e-12, (
            f"bar {bar_idx}: ur={ur} but expected {expected_ur} "
            f"from initial stop. Engine likely recomputed denominator "
            f"from stop_price_active — R-units are corrupted."
        )

    # (4) partial fired and carries correct R (initial stop basis)
    leg = t["partial_leg"]
    assert abs(leg["unrealized_r"] - 1.1) < 1e-12


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
