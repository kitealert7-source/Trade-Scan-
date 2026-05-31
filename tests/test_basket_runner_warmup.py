"""test_basket_runner_warmup.py — BasketRunner.warmup_bars mute contract.

Validates the 2026-05-30 warmup extension wired into the basket pipeline:
- BasketRunner.warmup_bars=0 default preserves byte-equivalence with
  pre-2026-05-30 behavior (no muting, every bar signal-eligible).
- BasketRunner.warmup_bars=N mutes leg check_entry/check_exit and skips
  rule.apply for bars [0, N), with original methods restored afterward.
- Fast path: warmup_bars=N opens at bar (N+1) instead of bar 1.
- Loader: _load_symbol_5m with leg_warmup_bars=0 returns the strict
  [start_date, end_date] window; with N>0, extends the lower bound by N
  index positions.

Tests use synthetic in-memory DataFrames where possible; the loader test
uses a real-RESEARCH read against a known symbol so the year-file
extension logic is exercised end-to-end.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.basket_runner import BasketLeg, BasketRunner  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthetic_df(n_bars: int = 100, start: str = "2024-01-01") -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame at 15m bars."""
    idx = pd.date_range(start=start, periods=n_bars, freq="15min", name="time")
    return pd.DataFrame({
        "open": 1.0,
        "high": 1.01,
        "low": 0.99,
        "close": 1.0,
        "volume": 100.0,
        "compression_5d": 5.0,
    }, index=idx)


class _NoopStrategy:
    """Minimal strategy that never signals. Records check_entry / check_exit
    calls per bar index for verification.
    """

    name = "noop_test"
    timeframe = "15m"
    # No `_basket_fast_path` marker — engine path required.

    def __init__(self, symbol: str, direction: int = +1) -> None:
        self.symbol = symbol
        self.direction = direction
        self.entry_call_indices: list[int] = []
        self.exit_call_indices: list[int] = []

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx) -> dict | None:
        self.entry_call_indices.append(int(ctx.index))
        return None

    def check_exit(self, ctx) -> bool:
        self.exit_call_indices.append(int(ctx.index))
        return False


class _RecordingRule:
    """Minimal rule that records the bar indices it was called for."""

    name = "test_recording_rule"

    def __init__(self, warmup: int = 0) -> None:
        self.apply_indices: list[int] = []
        self._warmup_to_declare = warmup

    def apply(self, legs, i, bar_ts) -> None:
        self.apply_indices.append(int(i))

    def required_warmup_bars(self) -> int:
        return self._warmup_to_declare


# ---------------------------------------------------------------------------
# Section A — BasketRunner constructor validation
# ---------------------------------------------------------------------------


def test_warmup_bars_default_is_zero():
    """A.1: BasketRunner created without warmup_bars defaults to 0."""
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(),
                  strategy=_NoopStrategy("EURUSD"), direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(),
                  strategy=_NoopStrategy("USDJPY"), direction=-1, lot=0.01),
    ]
    runner = BasketRunner(legs=legs)
    assert runner.warmup_bars == 0


def test_warmup_bars_negative_raises():
    """A.2: Negative warmup_bars rejected at __init__."""
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(),
                  strategy=_NoopStrategy("EURUSD"), direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(),
                  strategy=_NoopStrategy("USDJPY"), direction=-1, lot=0.01),
    ]
    with pytest.raises(ValueError, match="warmup_bars must be >= 0"):
        BasketRunner(legs=legs, warmup_bars=-1)


# ---------------------------------------------------------------------------
# Section B — Engine path mute behavior
# ---------------------------------------------------------------------------


def test_engine_path_warmup_zero_no_muting():
    """B.1: warmup_bars=0 → leg.strategy.check_entry called on EVERY bar.

    Byte-equivalence guarantee: pre-2026-05-30 behavior preserved when no
    warmup is requested.
    """
    n_bars = 30
    leg1_strat = _NoopStrategy("EURUSD")
    leg2_strat = _NoopStrategy("USDJPY")
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(n_bars),
                  strategy=leg1_strat, direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(n_bars),
                  strategy=leg2_strat, direction=-1, lot=0.01),
    ]
    rule = _RecordingRule()
    runner = BasketRunner(legs=legs, rules=[rule], warmup_bars=0)
    runner.run(fast_path=False)

    # All 30 bars touched by check_entry on both legs.
    assert leg1_strat.entry_call_indices == list(range(n_bars))
    assert leg2_strat.entry_call_indices == list(range(n_bars))
    # rule.apply also called on every bar.
    assert rule.apply_indices == list(range(n_bars))


def test_engine_path_warmup_mutes_first_n_bars():
    """B.2: warmup_bars=10 → leg signals + rule.apply skipped for bars [0, 10).

    The _NoopStrategy's entry_call_indices records EVERY call to its own
    check_entry method. The wrapped check_entry returns None for ctx.index
    < warmup_bars, so the noop's original method is bypassed for the first
    10 bars — entry_call_indices skips those positions.
    """
    n_bars = 30
    warmup = 10
    leg1_strat = _NoopStrategy("EURUSD")
    leg2_strat = _NoopStrategy("USDJPY")
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(n_bars),
                  strategy=leg1_strat, direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(n_bars),
                  strategy=leg2_strat, direction=-1, lot=0.01),
    ]
    rule = _RecordingRule()
    runner = BasketRunner(legs=legs, rules=[rule], warmup_bars=warmup)
    runner.run(fast_path=False)

    # Leg strategies' original check_entry NOT called for [0, 10).
    assert leg1_strat.entry_call_indices == list(range(warmup, n_bars))
    assert leg2_strat.entry_call_indices == list(range(warmup, n_bars))
    # Rule.apply only called for [warmup, n_bars).
    assert rule.apply_indices == list(range(warmup, n_bars))


def test_engine_path_warmup_restores_original_methods():
    """B.3: After run() completes, the wrapped check_entry / check_exit
    are unwound — calling them with ctx.index < warmup_bars no longer
    short-circuits; the original method is invoked unconditionally.

    Critical for callers that reuse the same strategy object across runs
    (e.g., tests, retests, sweeps). We can't use `is` identity (Python
    creates a fresh bound method on every attribute access) so we verify
    by behavior: after run(), check_entry on bar 0 reaches the underlying
    recording method instead of being muted.
    """
    n_bars = 30
    leg1_strat = _NoopStrategy("EURUSD")
    leg2_strat = _NoopStrategy("USDJPY")
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(n_bars),
                  strategy=leg1_strat, direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(n_bars),
                  strategy=leg2_strat, direction=-1, lot=0.01),
    ]
    runner = BasketRunner(legs=legs, warmup_bars=5)
    runner.run(fast_path=False)

    # Post-run, call check_entry with ctx.index=0 — if the wrapper is still
    # installed, the original method's recording side-effect is skipped
    # (muted return None). If the wrapper is unwound (correct), the
    # original method runs and records index=0.
    pre_call_count = len(leg1_strat.entry_call_indices)
    fake_ctx = MagicMock()
    fake_ctx.index = 0
    leg1_strat.check_entry(fake_ctx)
    post_call_count = len(leg1_strat.entry_call_indices)
    assert post_call_count == pre_call_count + 1, (
        "After run() the wrapper should be unwound: check_entry on bar 0 "
        "must invoke the original recording method, not the mute."
    )


# ---------------------------------------------------------------------------
# Section C — Fast path open shifts with warmup_bars
# ---------------------------------------------------------------------------


def test_fast_path_warmup_zero_opens_at_bar_one():
    """C.1: Fast path with warmup_bars=0 opens at bar 1 (pre-existing behavior).

    Uses the real ContinuousHoldStrategy from recycle_strategies (which sets
    `_basket_fast_path = True`) so we can run the fast path end-to-end.
    """
    from tools.recycle_strategies import ContinuousHoldStrategy
    n_bars = 50
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(n_bars),
                  strategy=ContinuousHoldStrategy("EURUSD"),
                  direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(n_bars),
                  strategy=ContinuousHoldStrategy("USDJPY"),
                  direction=-1, lot=0.01),
    ]
    runner = BasketRunner(legs=legs, warmup_bars=0)
    runner.run(fast_path=True)

    # Each leg should report entry_index == 1.
    for leg in legs:
        assert leg.state.in_pos is True
        assert leg.state.entry_index == 1


def test_fast_path_warmup_n_opens_at_bar_n_plus_one():
    """C.2: Fast path with warmup_bars=N opens at bar N+1.

    Same shape as C.1 but the entry is shifted by N to preserve the
    same warmup-then-open contract as the engine path.
    """
    from tools.recycle_strategies import ContinuousHoldStrategy
    n_bars = 50
    warmup = 15
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(n_bars),
                  strategy=ContinuousHoldStrategy("EURUSD"),
                  direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(n_bars),
                  strategy=ContinuousHoldStrategy("USDJPY"),
                  direction=-1, lot=0.01),
    ]
    runner = BasketRunner(legs=legs, warmup_bars=warmup)
    runner.run(fast_path=True)

    for leg in legs:
        assert leg.state.in_pos is True
        assert leg.state.entry_index == warmup + 1


def test_fast_path_insufficient_bars_with_warmup_raises():
    """C.3: Fast path requires at least (warmup + 2) bars (warmup + signal +
    fill). If the aligned index is smaller, the runner raises a clear error.
    """
    from tools.recycle_strategies import ContinuousHoldStrategy
    n_bars = 10
    warmup = 15  # exceeds available bars
    legs = [
        BasketLeg(symbol="EURUSD", df=_make_synthetic_df(n_bars),
                  strategy=ContinuousHoldStrategy("EURUSD"),
                  direction=+1, lot=0.01),
        BasketLeg(symbol="USDJPY", df=_make_synthetic_df(n_bars),
                  strategy=ContinuousHoldStrategy("USDJPY"),
                  direction=-1, lot=0.01),
    ]
    runner = BasketRunner(legs=legs, warmup_bars=warmup)
    with pytest.raises(RuntimeError, match="warmup="):
        runner.run(fast_path=True)


# ---------------------------------------------------------------------------
# Section D — PineRatioZRevRule.required_warmup_bars
# ---------------------------------------------------------------------------


def test_pine_rule_warmup_absolute_mode():
    """D.1: PineRatioZRevRule.required_warmup_bars() returns 2*n_window
    in absolute mode (mirrors the line-215 assertion).
    """
    from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule
    rule = PineRatioZRevRule(
        n_window=30,
        n_meta=100,
        z_entry=2.0,
        entry_mode="absolute",
        run_id="t",
        directive_id="t",
        basket_id="t",
    )
    assert rule.required_warmup_bars() == 60  # 2 * 30


def test_pine_rule_warmup_centered_mode():
    """D.2: PineRatioZRevRule.required_warmup_bars() returns n_window + n_meta
    in centered mode (centering uses past z_r values).
    """
    from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule
    rule = PineRatioZRevRule(
        n_window=30,
        n_meta=100,
        z_entry=2.0,
        entry_mode="centered",
        run_id="t",
        directive_id="t",
        basket_id="t",
    )
    assert rule.required_warmup_bars() == 130  # 30 + 100


def test_pine_rule_warmup_scales_with_params():
    """D.3: Changing n_window propagates to the warmup. No hard-coded constants."""
    from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule
    for n in (10, 50, 200):
        rule = PineRatioZRevRule(
            n_window=n,
            n_meta=100,
            z_entry=2.0,
            entry_mode="absolute",
            run_id="t",
            directive_id="t",
            basket_id="t",
        )
        assert rule.required_warmup_bars() == 2 * n, (
            f"Expected 2*{n}={2*n}, got {rule.required_warmup_bars()}"
        )


# ---------------------------------------------------------------------------
# Section E — _load_symbol_5m extension behavior (synthetic; no real I/O)
# ---------------------------------------------------------------------------


def test_load_symbol_5m_leg_warmup_zero_strict_filter(monkeypatch):
    """E.1: leg_warmup_bars=0 → strict [start_date, end_date] filter (default
    behavior; byte-equivalent to pre-2026-05-30).
    """
    from tools import basket_data_loader as bdl

    # Build a fake year-file that spans 2023-12-15 -> 2024-02-15 at 15m.
    full_idx = pd.date_range("2023-12-15", "2024-02-15", freq="15min", name="time")
    full_df = pd.DataFrame({
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0,
    }, index=full_idx)

    def fake_cache(symbol, year, timeframe):
        # Return all bars for the requested year only
        mask = full_df.index.year == year
        return full_df[mask].copy()

    monkeypatch.setattr(bdl, "_read_year_csv_cached", fake_cache)
    monkeypatch.setattr(bdl.Path, "is_dir", lambda self: True)

    df = bdl._load_symbol_5m("FAKE", "2024-01-15", "2024-02-01", timeframe="15m",
                              leg_warmup_bars=0)
    # First bar should be at-or-after start_date (strict filter)
    assert df.index[0] >= pd.Timestamp("2024-01-15")
    # Last bar should be at-or-before end_date
    assert df.index[-1] <= pd.Timestamp("2024-02-01")


def test_load_symbol_5m_leg_warmup_extends_lower_bound(monkeypatch):
    """E.2: leg_warmup_bars=N → loaded frame includes N index positions
    BEFORE the first bar at-or-after start_date (positional, not calendar).
    """
    from tools import basket_data_loader as bdl

    # Continuous 15m bars Dec 2023 - Feb 2024.
    full_idx = pd.date_range("2023-12-15", "2024-02-15", freq="15min", name="time")
    full_df = pd.DataFrame({
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0,
    }, index=full_idx)

    def fake_cache(symbol, year, timeframe):
        mask = full_df.index.year == year
        return full_df[mask].copy()

    monkeypatch.setattr(bdl, "_read_year_csv_cached", fake_cache)
    monkeypatch.setattr(bdl.Path, "is_dir", lambda self: True)

    warmup = 100
    df = bdl._load_symbol_5m("FAKE", "2024-01-15", "2024-02-01", timeframe="15m",
                              leg_warmup_bars=warmup)
    # First bar in the returned frame should be exactly `warmup` positions
    # before the first bar at-or-after start_date in the full series.
    first_in_window = full_idx.searchsorted(pd.Timestamp("2024-01-15"))
    expected_first_ts = full_idx[first_in_window - warmup]
    assert df.index[0] == expected_first_ts
    # End boundary unchanged.
    assert df.index[-1] <= pd.Timestamp("2024-02-01")


def test_load_symbol_5m_negative_warmup_raises():
    """E.3: leg_warmup_bars < 0 → ValueError."""
    from tools.basket_data_loader import _load_symbol_5m
    with pytest.raises(ValueError, match="leg_warmup_bars must be >= 0"):
        _load_symbol_5m("EURUSD", "2024-01-01", "2024-02-01", timeframe="15m",
                         leg_warmup_bars=-1)
