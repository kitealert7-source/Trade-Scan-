"""Tests for COINTREV v1.2 — leg strategy + rule + two-bar protocol.

Coverage targets:
  - Param validation (rule __post_init__)
  - Leg state machine: PROPOSED phase + per-bar atomicity + refuses double-propose
  - Rule approval phase: happy path β-sizing + strict-greater invariant
  - Rule rejection branches: BAD_DIRECTION, MIN_GAP_VIOLATION, BETA_NAN,
    NEUTRAL_BASKET_UNAVAILABLE, NO_NEXT_BAR
  - BASKET_OPEN transition: records event with β-sized lots, commits
    _last_entry_as_of, resets shared state
  - Exit logic: MEAN_REVERSION, REGIME_DEGRADATION ('breaking' + 'broken'),
    TIME_STOP — and priority order
  - Auto-discovery: rule resolves shared_armed_state from leg.strategy on
    first apply()

Fixtures use real OctaFX symbols (NZDUSD, USDCAD) so _compute_neutral_basket
hits the actual broker specs. Pair chosen because both have well-defined
broker specs and are pair-ordered alphabetically (canonical convention).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg
from tools.recycle_rules.cointegration_meanrev_v1_2 import (
    CointegrationMeanRevV1_2Rule,
)
from tools.recycle_strategies import (
    CointTriggerArmedState,
    CointTriggerLegStrategy,
)


# Canonical alphabetical pair — _compute_neutral_basket convention.
SYM_A, SYM_B = "NZDUSD", "USDCAD"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeCtx:
    """Minimal ContextView stand-in. Only .row and .get are used by the leg."""
    def __init__(self, row: pd.Series) -> None:
        self.row = row

    def get(self, col: str, default: Any = None) -> Any:
        if col in self.row.index:
            v = self.row[col]
            if isinstance(v, float) and np.isnan(v):
                return default
            return v
        return default


class _FakeRunner:
    def __init__(self, initial_lots: dict[str, float]) -> None:
        self._initial_lots = dict(initial_lots)


def _build_legs(
    n_bars: int = 30,
    *,
    trigger_bar_idx: int | None = None,
    direction: str = "LONG_SPREAD",
    beta_at_trigger: float = 0.75,
    regime_seq: list[str] | None = None,
    zscore_seq: list[float] | None = None,
    in_pos: bool = False,
    initial_lot: float = 0.01,
    start_ts: str = "2025-06-01 00:00:00",
) -> tuple[BasketLeg, BasketLeg, pd.DatetimeIndex, CointTriggerArmedState]:
    """Build two legs (NZDUSD, USDCAD) with synthetic cointegration columns.

    All columns are constant unless overridden:
      coint_trigger        : all False (set True at trigger_bar_idx)
      coint_direction      : '' (set at trigger bar)
      coint_beta_at_trigger: NaN (set at trigger bar)
      coint_regime         : 'cointegrated' (override via regime_seq)
      coint_current_zscore : 3.0 (override via zscore_seq)
    """
    idx = pd.date_range(start_ts, periods=n_bars, freq="15min")
    closes_a = np.linspace(0.65, 0.66, n_bars)
    closes_b = np.linspace(1.35, 1.36, n_bars)

    trigger_arr = np.full(n_bars, False, dtype=bool)
    direction_arr = np.array([""] * n_bars, dtype=object)
    beta_arr = np.full(n_bars, np.nan)
    z_at_trig_arr = np.full(n_bars, np.nan)

    if trigger_bar_idx is not None:
        trigger_arr[trigger_bar_idx] = True
        direction_arr[trigger_bar_idx] = direction
        beta_arr[trigger_bar_idx] = beta_at_trigger
        z_at_trig_arr[trigger_bar_idx] = 3.0

    if regime_seq is None:
        regime_arr = np.array(["cointegrated"] * n_bars, dtype=object)
    else:
        assert len(regime_seq) == n_bars
        regime_arr = np.array(regime_seq, dtype=object)

    if zscore_seq is None:
        zscore_arr = np.full(n_bars, 3.0)
    else:
        assert len(zscore_seq) == n_bars
        zscore_arr = np.array(zscore_seq, dtype=float)

    cols_common = {
        "coint_trigger":         trigger_arr,
        "coint_direction":       direction_arr,
        "coint_beta_at_trigger": beta_arr,
        "coint_z_at_trigger":    z_at_trig_arr,
        "coint_regime":          regime_arr,
        "coint_current_zscore":  zscore_arr,
    }

    df_a = pd.DataFrame(
        {"open": closes_a, "high": closes_a, "low": closes_a, "close": closes_a,
         **cols_common},
        index=idx,
    )
    df_b = pd.DataFrame(
        {"open": closes_b, "high": closes_b, "low": closes_b, "close": closes_b,
         **cols_common},
        index=idx,
    )

    shared = CointTriggerArmedState()
    leg_a = BasketLeg(SYM_A, lot=initial_lot, direction=+1, df=df_a,
                      strategy=CointTriggerLegStrategy(SYM_A, +1, armed_state=shared))
    leg_b = BasketLeg(SYM_B, lot=initial_lot, direction=-1, df=df_b,
                      strategy=CointTriggerLegStrategy(SYM_B, -1, armed_state=shared))

    for leg, closes in [(leg_a, closes_a), (leg_b, closes_b)]:
        leg.state = BarState()
        if in_pos:
            leg.state.in_pos = True
            leg.state.direction = leg.direction
            leg.state.entry_index = 0
            leg.state.entry_price = float(closes[0])
            leg.state.entry_market_state = {"initial_stop_price": 0.0}

    return leg_a, leg_b, idx, shared


def _step_leg_check_entries(legs: list[BasketLeg], bar_ts: pd.Timestamp) -> None:
    """Mimic the per-bar order: each leg's check_entry runs before rule.apply."""
    for leg in legs:
        row = leg.df.loc[bar_ts]
        leg.strategy.check_entry(_FakeCtx(row))


def _make_rule(
    *,
    min_gap_days_between_triggers: int = 5,
    exit_z: float = 1.0,
    time_stop_bars: int = 60,
    regime_exit_states: tuple[str, ...] = ("breaking", "broken"),
    initial_lot: float = 0.01,
    shared_armed_state: CointTriggerArmedState | None = None,
) -> CointegrationMeanRevV1_2Rule:
    rule = CointegrationMeanRevV1_2Rule(
        min_gap_days_between_triggers=min_gap_days_between_triggers,
        exit_z=exit_z,
        time_stop_bars=time_stop_bars,
        regime_exit_states=regime_exit_states,
        default_initial_lot=initial_lot,
        shared_armed_state=shared_armed_state,
        run_id="TEST", directive_id="TEST_DIR", basket_id="TEST_BASKET",
    )
    rule.basket_runner = _FakeRunner({SYM_A: initial_lot, SYM_B: initial_lot})
    return rule


def _find_event(events: list[dict], action: str, **filters):
    """First event matching action + filter kwargs; raises if none."""
    for ev in events:
        if ev.get("action") != action:
            continue
        if all(ev.get(k) == v for k, v in filters.items()):
            return ev
    raise AssertionError(
        f"No event with action={action!r}, filters={filters}. "
        f"Got {[(e.get('action'), e.get('reason')) for e in events]}"
    )


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------


def test_rule_instantiates_with_defaults():
    rule = CointegrationMeanRevV1_2Rule(
        run_id="r", directive_id="d", basket_id="b",
    )
    assert rule.name == "cointegration_meanrev_v1_2"
    assert rule.version == 1
    assert rule.exit_z == 1.0
    assert rule.time_stop_bars == 60
    assert rule.regime_exit_states == ("breaking", "broken")
    assert rule.min_gap_days_between_triggers == 5


@pytest.mark.parametrize("kwarg, value, match", [
    ("min_gap_days_between_triggers", -1, "min_gap_days_between_triggers must be >= 0"),
    ("exit_z",                         0.0, "exit_z must be > 0"),
    ("exit_z",                        -1.0, "exit_z must be > 0"),
    ("time_stop_bars",                   0, "time_stop_bars must be > 0"),
    ("regime_exit_states",              (), "regime_exit_states must be a non-empty"),
    ("initial_notional_usd",          -1.0, "initial_notional_usd must be > 0"),
    ("default_initial_lot",              0.0, "default_initial_lot must be > 0"),
])
def test_rule_param_validation(kwarg, value, match):
    with pytest.raises(ValueError, match=match):
        CointegrationMeanRevV1_2Rule(
            run_id="r", directive_id="d", basket_id="b", **{kwarg: value},
        )


# ---------------------------------------------------------------------------
# Leg state machine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction_str, expected_dir", [
    ("LONG_SPREAD",  +1),
    ("SHORT_SPREAD", -1),
])
def test_leg_proposes_on_trigger(direction_str, expected_dir):
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=5, trigger_bar_idx=2, direction=direction_str,
    )
    # Trigger bar — both legs evaluate; only first should write state.
    _step_leg_check_entries([leg_a, leg_b], idx[2])
    assert shared.pending_trigger_ts == idx[2]
    assert shared.pending_trigger_as_of == idx[2].normalize()
    assert shared.proposed_direction == expected_dir
    # Leg returned NO signal on trigger bar (proposal phase, not fire).
    sig_a = leg_a.strategy.check_entry(_FakeCtx(leg_a.df.loc[idx[2]]))
    # Per-bar atomicity: second call on same bar is a no-op for state but
    # the fire check also returns None (not yet approved).
    assert sig_a is None


def test_leg_refuses_double_propose_while_pending():
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=8, trigger_bar_idx=2, direction="LONG_SPREAD",
    )
    # Plant a second trigger on bar 5 — leg should NOT overwrite pending state.
    leg_a.df.iloc[5, leg_a.df.columns.get_loc("coint_trigger")] = True
    leg_a.df.iloc[5, leg_a.df.columns.get_loc("coint_direction")] = "SHORT_SPREAD"
    leg_b.df.iloc[5, leg_b.df.columns.get_loc("coint_trigger")] = True
    leg_b.df.iloc[5, leg_b.df.columns.get_loc("coint_direction")] = "SHORT_SPREAD"

    _step_leg_check_entries([leg_a, leg_b], idx[2])
    pending_after_first = shared.pending_trigger_ts
    proposed_dir_after_first = shared.proposed_direction
    _step_leg_check_entries([leg_a, leg_b], idx[5])
    # Pending unchanged — original proposal not overwritten.
    assert shared.pending_trigger_ts == pending_after_first
    assert shared.proposed_direction == proposed_dir_after_first


def test_leg_per_bar_atomicity():
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=5, trigger_bar_idx=2, direction="LONG_SPREAD",
    )
    leg_a.strategy.check_entry(_FakeCtx(leg_a.df.loc[idx[2]]))
    pending_after_first = shared.pending_trigger_ts
    # last_processed_ts is set; second leg sees it and skips arming block.
    assert shared.last_processed_ts == idx[2]
    leg_b.strategy.check_entry(_FakeCtx(leg_b.df.loc[idx[2]]))
    assert shared.pending_trigger_ts == pending_after_first


# ---------------------------------------------------------------------------
# Approval phase (rule)
# ---------------------------------------------------------------------------


def test_rule_approves_clean_trigger_and_sizes_lots():
    """Happy path: leg proposes → rule approves → β-sizes lots → asserts
    approved_fire_ts > pending_trigger_ts."""
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=5, trigger_bar_idx=2, beta_at_trigger=0.75,
    )
    rule = _make_rule(shared_armed_state=shared)
    initial_lot_a, initial_lot_b = leg_a.lot, leg_b.lot

    # Bar 0, 1: no trigger; rule.apply emits AWAITING_ENTRY.
    for i in (0, 1):
        _step_leg_check_entries([leg_a, leg_b], idx[i])
        rule.apply([leg_a, leg_b], i, idx[i])
    assert shared.pending_trigger_ts is None

    # Bar 2: trigger fires → propose + approve same bar.
    _step_leg_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])

    assert shared.approved is True
    assert shared.approved_fire_ts == idx[3]
    # Strict-greater invariant
    assert shared.approved_fire_ts > shared.pending_trigger_ts

    # Lots have been mutated to β-sized values (non-default).
    assert (leg_a.lot, leg_b.lot) != (initial_lot_a, initial_lot_b)
    assert leg_a.lot > 0 and leg_b.lot > 0

    # APPROVED event recorded with β + lots.
    approved_ev = _find_event(rule.recycle_events, "APPROVED")
    assert approved_ev["beta"] == pytest.approx(0.75)
    assert approved_ev["approved_fire_ts"] == idx[3]
    assert approved_ev["proposed_direction"] == +1
    assert set(approved_ev["lots_by_symbol"].keys()) == {SYM_A, SYM_B}


def test_rule_rejects_min_gap_violation():
    """Second trigger 2 days after the first is rejected when
    min_gap_days_between_triggers=5."""
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=400, trigger_bar_idx=10, beta_at_trigger=0.75,
        start_ts="2025-06-01 00:00:00",
    )
    # Inject a SECOND trigger 2 calendar days later (=2*96 bars on 15min grid).
    second_trigger_idx = 10 + 2 * 96
    leg_a.df.iloc[second_trigger_idx, leg_a.df.columns.get_loc("coint_trigger")] = True
    leg_a.df.iloc[second_trigger_idx, leg_a.df.columns.get_loc("coint_direction")] = "LONG_SPREAD"
    leg_a.df.iloc[second_trigger_idx, leg_a.df.columns.get_loc("coint_beta_at_trigger")] = 0.75
    leg_b.df.iloc[second_trigger_idx, leg_b.df.columns.get_loc("coint_trigger")] = True
    leg_b.df.iloc[second_trigger_idx, leg_b.df.columns.get_loc("coint_direction")] = "LONG_SPREAD"
    leg_b.df.iloc[second_trigger_idx, leg_b.df.columns.get_loc("coint_beta_at_trigger")] = 0.75

    rule = _make_rule(shared_armed_state=shared, min_gap_days_between_triggers=5)

    # Simulate the first cycle in full: propose → approve → fire → open →
    # exit (clean mean-reversion at bar 20). Then trigger #2 fires at bar 202
    # (2 days later) and should be rejected.
    # First trigger → approve → open.
    _step_leg_check_entries([leg_a, leg_b], idx[10])
    rule.apply([leg_a, leg_b], 10, idx[10])
    # Engine opens at bar 11; here we manually transition state.
    for leg in (leg_a, leg_b):
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 11
        leg.state.entry_price = float(leg.df.iloc[11]["close"])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    # Bar 11 = fire bar; rule processes BASKET_OPEN.
    _step_leg_check_entries([leg_a, leg_b], idx[11])
    rule.apply([leg_a, leg_b], 11, idx[11])
    assert rule._basket_open is True
    assert rule._last_entry_as_of == idx[10].normalize()

    # Force a mean-reversion exit at bar 20 (z=0 < 1.0).
    leg_a.df.iloc[20, leg_a.df.columns.get_loc("coint_current_zscore")] = 0.0
    leg_b.df.iloc[20, leg_b.df.columns.get_loc("coint_current_zscore")] = 0.0
    rule.apply([leg_a, leg_b], 20, idx[20])
    assert rule._basket_open is False  # exited

    # Now the second trigger fires at bar 202 (2 days after the first).
    _step_leg_check_entries([leg_a, leg_b], idx[second_trigger_idx])
    rule.apply([leg_a, leg_b], second_trigger_idx, idx[second_trigger_idx])

    reject_ev = _find_event(rule.recycle_events, "REJECTED",
                             reason="MIN_GAP_VIOLATION")
    assert reject_ev["gap_days"] == 2
    assert rule._n_rejected_min_gap == 1
    # State reset after rejection.
    assert shared.pending_trigger_ts is None


def test_rule_rejects_beta_nan():
    """Trigger with NaN β is rejected with BETA_NAN."""
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=5, trigger_bar_idx=2, beta_at_trigger=float("nan"),
    )
    rule = _make_rule(shared_armed_state=shared)
    _step_leg_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])
    _find_event(rule.recycle_events, "REJECTED", reason="BETA_NAN")
    assert rule._n_rejected_beta_unavailable == 1
    assert shared.pending_trigger_ts is None


def test_rule_rejects_no_next_bar_at_end_of_series():
    """Trigger on the LAST bar in the series → no next bar → reject NO_NEXT_BAR."""
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=5, trigger_bar_idx=4, beta_at_trigger=0.75,
    )
    rule = _make_rule(shared_armed_state=shared)
    _step_leg_check_entries([leg_a, leg_b], idx[4])
    rule.apply([leg_a, leg_b], 4, idx[4])
    _find_event(rule.recycle_events, "REJECTED", reason="NO_NEXT_BAR")
    assert rule._n_rejected_no_next_bar == 1


def test_strict_greater_invariant_holds_on_every_approval():
    """approved_fire_ts > pending_trigger_ts must hold on every approval —
    asserted inside _maybe_approve; this test confirms the assert hasn't
    been weakened."""
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=5, trigger_bar_idx=2, beta_at_trigger=0.75,
    )
    rule = _make_rule(shared_armed_state=shared)
    _step_leg_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])
    # Confirm the invariant directly.
    assert shared.approved_fire_ts > shared.pending_trigger_ts
    assert (shared.approved_fire_ts - shared.pending_trigger_ts) == pd.Timedelta(minutes=15)


# ---------------------------------------------------------------------------
# BASKET_OPEN transition
# ---------------------------------------------------------------------------


def test_basket_open_records_event_and_clears_shared_state():
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=10, trigger_bar_idx=2, beta_at_trigger=0.75,
    )
    rule = _make_rule(shared_armed_state=shared)
    # Bar 2: propose + approve
    _step_leg_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])
    # Bar 3: fire (engine opens at next_bar_open = bar 4 in production;
    # simplify here by transitioning in_pos directly between bars).
    _step_leg_check_entries([leg_a, leg_b], idx[3])
    rule.apply([leg_a, leg_b], 3, idx[3])

    # Engine fill at bar 4: transition in_pos True, then rule sees it.
    for leg in (leg_a, leg_b):
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 4
        leg.state.entry_price = float(leg.df.iloc[4]["close"])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    rule.apply([leg_a, leg_b], 4, idx[4])

    assert rule._basket_open is True
    assert rule._last_entry_as_of == idx[2].normalize()
    open_ev = _find_event(rule.recycle_events, "BASKET_OPEN")
    assert open_ev["entry_beta"] == pytest.approx(0.75)
    assert open_ev["approved_as_of"] == idx[2].normalize()
    # Shared state was reset on BASKET_OPEN.
    assert shared.pending_trigger_ts is None
    assert shared.approved_fire_ts is None
    assert shared.approved is False


# ---------------------------------------------------------------------------
# Exit logic
# ---------------------------------------------------------------------------


def _build_legs_in_position(*, zscore: float = 3.0, regime: str = "cointegrated",
                            entry_bar_idx: int = 0, n_bars: int = 100):
    """Shortcut: build legs already in-position with a configurable post-entry
    zscore + regime sequence (constant after entry_bar_idx)."""
    zscore_seq = [3.0] * n_bars
    regime_seq = ["cointegrated"] * n_bars
    for i in range(entry_bar_idx, n_bars):
        zscore_seq[i] = zscore
        regime_seq[i] = regime
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=n_bars, in_pos=True,
        zscore_seq=zscore_seq, regime_seq=regime_seq,
    )
    return leg_a, leg_b, idx, shared


def test_exit_mean_reversion_fires_when_abs_z_at_or_below_exit_z():
    leg_a, leg_b, idx, shared = _build_legs_in_position(zscore=0.5)
    rule = _make_rule(shared_armed_state=shared, exit_z=1.0)
    rule._basket_open = True
    rule._entry_bar_idx = 0
    rule._last_entry_as_of = idx[0].normalize()
    rule.apply([leg_a, leg_b], 5, idx[5])
    liq = _find_event(rule.recycle_events, "LIQUIDATE", reason="MEAN_REVERSION")
    assert liq["exit_zscore"] == pytest.approx(0.5)
    assert rule._n_mean_rev_exits == 1
    assert leg_a.state.in_pos is False and leg_b.state.in_pos is False


@pytest.mark.parametrize("bad_regime", ["breaking", "broken"])
def test_exit_regime_degradation(bad_regime):
    leg_a, leg_b, idx, shared = _build_legs_in_position(
        zscore=3.0, regime=bad_regime,  # z high → mean_rev doesn't fire
    )
    rule = _make_rule(shared_armed_state=shared, exit_z=1.0)
    rule._basket_open = True
    rule._entry_bar_idx = 0
    rule._last_entry_as_of = idx[0].normalize()
    rule.apply([leg_a, leg_b], 5, idx[5])
    liq = _find_event(rule.recycle_events, "LIQUIDATE",
                       reason="REGIME_DEGRADATION")
    assert liq["exit_regime"] == bad_regime
    assert rule._n_regime_exits == 1


def test_exit_time_stop_fires_at_elapsed_threshold():
    leg_a, leg_b, idx, shared = _build_legs_in_position(zscore=3.0)
    rule = _make_rule(shared_armed_state=shared, exit_z=1.0, time_stop_bars=10)
    rule._basket_open = True
    rule._entry_bar_idx = 0
    rule._last_entry_as_of = idx[0].normalize()
    rule.apply([leg_a, leg_b], 10, idx[10])  # elapsed = 10 - 0 = 10 >= 10
    liq = _find_event(rule.recycle_events, "LIQUIDATE", reason="TIME_STOP")
    assert liq["elapsed_bars"] == 10
    assert rule._n_time_stops == 1


def test_exit_priority_mean_reversion_wins_over_regime_and_time():
    """All three conditions met at the same bar — MEAN_REVERSION fires first."""
    leg_a, leg_b, idx, shared = _build_legs_in_position(
        zscore=0.5, regime="broken",  # both mean-rev and regime would fire
    )
    rule = _make_rule(shared_armed_state=shared, exit_z=1.0, time_stop_bars=3)
    rule._basket_open = True
    rule._entry_bar_idx = 0
    rule._last_entry_as_of = idx[0].normalize()
    rule.apply([leg_a, leg_b], 5, idx[5])  # elapsed > time_stop too
    liq = _find_event(rule.recycle_events, "LIQUIDATE", reason="MEAN_REVERSION")
    assert rule._n_mean_rev_exits == 1
    assert rule._n_regime_exits == 0
    assert rule._n_time_stops == 0


def test_exit_priority_regime_wins_over_time_stop():
    """When mean-rev doesn't fire but regime does, regime beats time-stop."""
    leg_a, leg_b, idx, shared = _build_legs_in_position(
        zscore=3.0, regime="broken",
    )
    rule = _make_rule(shared_armed_state=shared, exit_z=1.0, time_stop_bars=3)
    rule._basket_open = True
    rule._entry_bar_idx = 0
    rule._last_entry_as_of = idx[0].normalize()
    rule.apply([leg_a, leg_b], 5, idx[5])
    liq = _find_event(rule.recycle_events, "LIQUIDATE",
                       reason="REGIME_DEGRADATION")
    assert rule._n_regime_exits == 1
    assert rule._n_time_stops == 0


# ---------------------------------------------------------------------------
# Auto-discovery of shared state
# ---------------------------------------------------------------------------


def test_auto_discovery_resolves_shared_state_from_leg_strategy():
    """When the rule is constructed without explicit shared_armed_state,
    apply() should discover it from leg.strategy.armed_state on first call."""
    leg_a, leg_b, idx, shared = _build_legs(n_bars=3)
    # Build rule WITHOUT shared_armed_state.
    rule = _make_rule(shared_armed_state=None)
    assert rule.shared_armed_state is None
    rule.apply([leg_a, leg_b], 0, idx[0])
    assert rule.shared_armed_state is shared


# ---------------------------------------------------------------------------
# Cross-region market-holiday divergence (regression test for 2026-05-24 bug)
# ---------------------------------------------------------------------------


def test_approval_uses_intersected_leg_indices_skips_holiday_bar():
    """Daily-TF cross-region pairs diverge on market holidays (e.g., UK100
    misses 2025-05-26 UK Spring Bank Holiday but EUSTX50 has it).

    Bug (fixed 2026-05-24): _maybe_approve set approved_fire_ts from
    legs[0].df.index alone — picking a bar BasketRunner's intersection
    iteration never visits. Leg's check_entry never saw a matching ts,
    state stuck, only the FIRST trigger of the year ever approved.

    Fix: intersect all legs' indices when resolving next_bar_ts.

    Regression: ensure approved_fire_ts skips the gap to the next
    bar present in BOTH legs.
    """
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=10, trigger_bar_idx=2, beta_at_trigger=0.75,
    )
    # Simulate leg_b missing the bar immediately after the trigger.
    # In production this models a cross-region market holiday.
    leg_b.df = leg_b.df.drop(idx[3])

    rule = _make_rule(shared_armed_state=shared)
    _step_leg_check_entries([leg_a, leg_b], idx[2])
    rule.apply([leg_a, leg_b], 2, idx[2])

    # Pre-fix behavior would have set approved_fire_ts = idx[3]
    # (which leg_b is missing) → leg's check_entry never matches → stall.
    # Post-fix: skip idx[3], land on idx[4] which BOTH legs have.
    assert shared.approved is True
    assert shared.approved_fire_ts == idx[4]
    # Strict-greater invariant still holds.
    assert shared.approved_fire_ts > shared.pending_trigger_ts


def test_approval_rejects_no_next_bar_when_one_leg_truncated_after_trigger():
    """When ONE leg has no bars after the trigger bar, the intersection
    of post-trigger indices is empty → NO_NEXT_BAR rejection (not a stall).

    Catches the worst-case end-of-data + divergent-leg scenario.
    """
    leg_a, leg_b, idx, shared = _build_legs(
        n_bars=10, trigger_bar_idx=5, beta_at_trigger=0.75,
    )
    # leg_b has no bars after the trigger bar (idx[5]).
    leg_b.df = leg_b.df.loc[:idx[5]]

    rule = _make_rule(shared_armed_state=shared)
    _step_leg_check_entries([leg_a, leg_b], idx[5])
    rule.apply([leg_a, leg_b], 5, idx[5])

    _find_event(rule.recycle_events, "REJECTED", reason="NO_NEXT_BAR")
    assert rule._n_rejected_no_next_bar == 1
    # State must be reset after rejection (no lingering pending proposal).
    assert shared.pending_trigger_ts is None
    assert shared.approved_fire_ts is None

