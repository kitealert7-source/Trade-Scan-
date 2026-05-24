"""Tests for pine_ratio_zrev_v1 — BASKET_OPEN direction-sync regression.

Scope: minimal regression coverage for the leg_direction_flip_bug fix
(2026-05-24). Verifies that on BASKET_OPEN the rule syncs
`leg.direction = leg.state.direction` so the inherited PnL math
(_leg_pnl_usd_universal reads leg.direction) sees the correct
per-cycle direction on SHORT_SPREAD cycles.

This mirrors the pattern in:
  - tests/test_h3_spread_v2_harvest.py::test_v2_bidirectional_mutates_leg_direction_on_open
  - tests/test_cointegration_meanrev_v1_2.py::test_basket_open_syncs_leg_direction_to_state_direction

Broader coverage (z_r computation, reversal detection, etc.) is implicit
through the directive-level pipeline runs; this file's purpose is to
prevent regression of the specific accounting bug.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy


SYM_A, SYM_B = "EURUSD", "USDJPY"


class _FakeRunner:
    def __init__(self, initial_lots: dict[str, float]) -> None:
        self._initial_lots = dict(initial_lots)


def _build_legs_with_signal(
    *,
    n_bars: int = 20,
    signal_bar_idx: int = 2,
    signal_value: int = -1,
    initial_lot: float = 0.01,
) -> tuple[BasketLeg, BasketLeg, pd.DatetimeIndex, PineZRevArmedState]:
    """Build two legs with pine_zrev_signal column pre-attached.

    Bypasses _attach_z_r by pre-populating the signal column and
    pre-setting rule._z_r_attached = True in the test body. The
    r_bar column is set to a valid positive value so _maybe_approve
    proceeds past its warmup-NaN guard.
    """
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="1D")
    closes_a = np.linspace(1.1000, 1.1100, n_bars)
    closes_b = np.linspace(150.0, 151.0, n_bars)

    signal_arr = np.zeros(n_bars, dtype=int)
    signal_arr[signal_bar_idx] = signal_value
    r_bar_arr = np.full(n_bars, 0.00733)   # constant non-NaN positive

    df_a = pd.DataFrame(
        {"open": closes_a, "high": closes_a, "low": closes_a, "close": closes_a,
         "pine_zrev_signal": signal_arr, "pine_zrev_r_bar": r_bar_arr},
        index=idx,
    )
    df_b = pd.DataFrame(
        {"open": closes_b, "high": closes_b, "low": closes_b, "close": closes_b,
         "pine_zrev_signal": signal_arr, "pine_zrev_r_bar": r_bar_arr},
        index=idx,
    )

    shared = PineZRevArmedState()
    leg_a = BasketLeg(SYM_A, lot=initial_lot, direction=+1, df=df_a,
                      strategy=PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    leg_b = BasketLeg(SYM_B, lot=initial_lot, direction=-1, df=df_b,
                      strategy=PineZRevLegStrategy(SYM_B, -1, armed_state=shared))

    for leg in (leg_a, leg_b):
        leg.state = BarState()

    return leg_a, leg_b, idx, shared


def _make_rule(shared: PineZRevArmedState, initial_lot: float = 0.01,
               ) -> PineRatioZRevRule:
    rule = PineRatioZRevRule(
        n_window=10,
        z_entry=2.0,
        entry_mode="absolute",   # skip n_meta centering for test simplicity
        default_initial_lot=initial_lot,
        target_notional_per_leg_usd=10_000.0,
        shared_armed_state=shared,
        run_id="TEST", directive_id="TEST_DIR", basket_id="TEST_BASKET",
    )
    rule.basket_runner = _FakeRunner({SYM_A: initial_lot, SYM_B: initial_lot})
    rule._z_r_attached = True   # bypass _attach_z_r (we pre-populated columns)
    return rule


def _fake_check_entries(legs: list[BasketLeg], bar_ts: pd.Timestamp) -> None:
    """Mimic per-bar order: leg.check_entry runs before rule.apply."""
    from types import SimpleNamespace
    for leg in legs:
        row = leg.df.loc[bar_ts]
        ctx = SimpleNamespace(row=row, get=lambda k, default=None: row.get(k, default))
        leg.strategy.check_entry(ctx)


def test_basket_open_effective_direction_short_spread():
    """SHORT_SPREAD cycle: state.direction is OPPOSITE of leg.direction.
    leg.effective_direction must return state.direction (cycle-aware) so
    that inherited _leg_pnl_usd_universal accounts for the correct sign.
    leg.direction itself MUST stay at YAML BASE (immutable invariant)."""
    leg_a, leg_b, idx, shared = _build_legs_with_signal(
        n_bars=10, signal_bar_idx=2, signal_value=-1,
    )
    rule = _make_rule(shared)

    # Bar 2: leg proposes, rule approves.
    _fake_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])
    assert shared.approved is True
    assert shared.approved_fire_ts == idx[3]

    # Bar 3: leg fires (engine queues open at bar 4).
    _fake_check_entries([leg_a, leg_b], idx[3])
    rule.apply([leg_a, leg_b], 3, idx[3])

    # Bar 4: engine opens with sign-flipped state.direction.
    initial_a = leg_a.direction   # +1
    initial_b = leg_b.direction   # -1
    for leg in (leg_a, leg_b):
        leg.state.in_pos = True
        leg.state.direction = -leg.direction   # SHORT_SPREAD inversion
        leg.state.entry_index = 4
        leg.state.entry_price = float(leg.df.iloc[4]["close"])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    rule.apply([leg_a, leg_b], 4, idx[4])

    # Invariant: leg.direction stays at YAML BASE (no mutation).
    assert leg_a.direction == initial_a, (
        f"leg_a.direction was mutated from {initial_a} to {leg_a.direction}"
    )
    assert leg_b.direction == initial_b, (
        f"leg_b.direction was mutated from {initial_b} to {leg_b.direction}"
    )
    # Cycle-aware accessor returns state.direction during cycle.
    assert leg_a.effective_direction == -1, (
        f"effective_direction must reflect cycle: state.direction=-1, got "
        f"{leg_a.effective_direction}"
    )
    assert leg_b.effective_direction == +1
    # _basket_direction tracker reflects the cycle direction.
    assert rule._basket_direction == -1
    # BASKET_OPEN event records cycle-aware leg_directions.
    open_evt = next(e for e in rule.recycle_events if e.get("action") == "BASKET_OPEN")
    assert open_evt["leg_directions"][SYM_A] == -1
    assert open_evt["leg_directions"][SYM_B] == +1


def test_basket_open_long_spread_effective_matches_base():
    """LONG_SPREAD cycle: state.direction == leg.direction →
    effective_direction == leg.direction. Bug-class-irrelevant happy path."""
    leg_a, leg_b, idx, shared = _build_legs_with_signal(
        n_bars=10, signal_bar_idx=2, signal_value=+1,
    )
    rule = _make_rule(shared)

    _fake_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])
    _fake_check_entries([leg_a, leg_b], idx[3])
    rule.apply([leg_a, leg_b], 3, idx[3])

    for leg in (leg_a, leg_b):
        leg.state.in_pos = True
        leg.state.direction = leg.direction   # LONG_SPREAD = BASE-aligned
        leg.state.entry_index = 4
        leg.state.entry_price = float(leg.df.iloc[4]["close"])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    rule.apply([leg_a, leg_b], 4, idx[4])

    assert leg_a.direction == +1 and leg_a.effective_direction == +1
    assert leg_b.direction == -1 and leg_b.effective_direction == -1
    assert rule._basket_direction == +1
