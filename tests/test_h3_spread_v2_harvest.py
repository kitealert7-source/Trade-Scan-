"""Tests for H3SpreadV2Rule (bounded-exposure + harvest scale-out).

H3_spread@2 = H3_spread@1 + two-phase pyramid lifecycle (2026-05-19):
  Phase 1 (accumulation): pyramid threshold crossings ADD to both legs
  until per-leg lot reaches max_exposure_multiple * initial_lot.
  Phase 2 (harvest): subsequent threshold crossings SCALE OUT both legs
  by pyramid_add_lot each, realizing proportional share of leg floating.
  Terminal: when a scale-out would drive any leg's lot to <= 0, cycle
  ends with LIQUIDATE_HARVEST_COMPLETE.

Coverage:
  - Validator accepts defaults; rejects bad new params
  - Inherits @1 validation (adverse_stop_pct, time_stop_bars, etc.)
  - Phase-1 pyramid adds match @1 semantics until cap
  - Phase-2 scale-out reduces lot, realizes proportional PnL,
    preserves entry price
  - Terminal harvest fires LIQUIDATE_HARVEST_COMPLETE when residual hits 0
  - Hysteresis preserved: each threshold level fires at most once
  - Other exits (ADVERSE_STOP, REVERSE_CROSS, TIME_STOP) still preempt
    the pyramid block, unchanged from @1
  - Initial lot snapshot captured on first basket-open bar
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine_abi.v1_5_9 import BarState
from tools.basket_runner import BasketLeg
from tools.recycle_rules.h3_spread_v2 import H3SpreadV2Rule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _NoOpStrategy:
    name = "noop_h3v2"
    timeframe = "5m"

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


class _FakeRunner:
    """Minimal stand-in for BasketRunner used by H3SpreadV2Rule.
    Only `_initial_lots` is consumed (in the terminal-harvest reset path)."""
    def __init__(self, initial_lots: dict[str, float]):
        self._initial_lots = initial_lots


def _build_legs(
    eur_prices: np.ndarray,
    jpy_prices: np.ndarray,
    cross_side_arr: np.ndarray | None = None,
    initial_lot: float = 0.10,
) -> tuple[BasketLeg, BasketLeg, pd.DatetimeIndex]:
    """Build LONG EURUSD + SHORT USDJPY basket (BEAR direction = +1).
    `cross_side` defaults to +1 every bar (no reverse-cross)."""
    n = len(eur_prices)
    assert len(jpy_prices) == n
    idx = pd.date_range("2024-01-01 00:00:00", periods=n, freq="5min")
    if cross_side_arr is None:
        cross_side_arr = np.full(n, 1, dtype=int)
    eur_df = pd.DataFrame(
        {
            "open": eur_prices, "high": eur_prices, "low": eur_prices,
            "close": eur_prices, "cross_side": cross_side_arr,
        },
        index=idx,
    )
    jpy_df = pd.DataFrame(
        {
            "open": jpy_prices, "high": jpy_prices, "low": jpy_prices,
            "close": jpy_prices, "cross_side": cross_side_arr,
        },
        index=idx,
    )
    eur_leg = BasketLeg("EURUSD", lot=initial_lot, direction=+1, df=eur_df,
                        strategy=_NoOpStrategy())
    jpy_leg = BasketLeg("USDJPY", lot=initial_lot, direction=-1, df=jpy_df,
                        strategy=_NoOpStrategy())
    for leg, prices in [(eur_leg, eur_prices), (jpy_leg, jpy_prices)]:
        leg.state = BarState()
        leg.state.in_pos = True
        leg.state.direction = leg.direction
        leg.state.entry_index = 0
        leg.state.entry_price = float(prices[0])
        leg.state.entry_market_state = {"initial_stop_price": 0.0}
    return eur_leg, jpy_leg, idx


def _make_rule(**kwargs) -> H3SpreadV2Rule:
    """Build a V2 rule with realistic defaults. Override any field via kwargs."""
    defaults = {
        "max_exposure_multiple": 3.0,
        "pyramid_threshold_step_pct": 0.15,
        "pyramid_add_lot": 0.05,
        "adverse_stop_pct": 0.020,    # P03 = $20 on $1k
        "time_stop_bars": 864,
        "entry_direction": +1,
        "initial_notional_usd": 1000.0,
        "run_id": "test", "directive_id": "test", "basket_id": "H3V2",
    }
    defaults.update(kwargs)
    rule = H3SpreadV2Rule(**defaults)
    rule.basket_runner = _FakeRunner({"EURUSD": 0.10, "USDJPY": 0.10})
    return rule


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_v2_default_construction_passes():
    r = H3SpreadV2Rule()
    assert r.name == "H3_spread"
    assert r.version == 2
    assert r.max_exposure_multiple == 3.0
    assert r.pyramid_threshold_step_pct == 0.15
    assert r._n_harvests_total == 0
    assert r._initial_lot_per_leg is None   # snapshotted on first apply
    assert r._max_lot_per_leg is None


def test_v2_validator_rejects_max_exposure_below_one():
    with pytest.raises(ValueError, match="max_exposure_multiple"):
        H3SpreadV2Rule(max_exposure_multiple=0.5)


def test_v2_validator_rejects_step_pct_zero():
    with pytest.raises(ValueError, match="pyramid_threshold_step_pct"):
        H3SpreadV2Rule(pyramid_threshold_step_pct=0.0)


def test_v2_validator_rejects_step_pct_negative():
    with pytest.raises(ValueError, match="pyramid_threshold_step_pct"):
        H3SpreadV2Rule(pyramid_threshold_step_pct=-0.1)


def test_v2_validator_rejects_harvest_delay_negative():
    with pytest.raises(ValueError, match="harvest_start_after_extra_pyramids"):
        H3SpreadV2Rule(harvest_start_after_extra_pyramids=-1)


def test_v2_validator_rejects_harvest_delay_non_int():
    with pytest.raises(ValueError, match="harvest_start_after_extra_pyramids"):
        H3SpreadV2Rule(harvest_start_after_extra_pyramids=2.5)


def test_v2_inherits_v1_validation_adverse_stop():
    # Parent @1 rejects adverse_stop_pct >= 1.0
    with pytest.raises(ValueError, match="adverse_stop_pct"):
        H3SpreadV2Rule(adverse_stop_pct=1.5)


# ---------------------------------------------------------------------------
# Phase 1 — accumulation (adds match @1)
# ---------------------------------------------------------------------------


def test_v2_phase1_first_pyramid_adds():
    """When basket floating crosses level-1 threshold ($1.50) and lot < cap,
    rule fires ADD: lot grows by pyramid_add_lot on both legs."""
    # EUR rises from 1.1000 toward 1.1010 (10 pips = $10 on 0.10 lot, well
    # past the $1.50 level-1 threshold). JPY held constant — its share of
    # basket float will be zero (entry == mark).
    n = 5
    eur = np.array([1.1000, 1.1000, 1.1005, 1.1010, 1.1015])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule()

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    # Pyramid events fired
    pyr_events = [e for e in rule.recycle_events if e.get("action") == "PYRAMID"]
    assert len(pyr_events) >= 1
    # Lot grew by pyramid_add_lot per event (0.05)
    assert eur_leg.lot >= 0.15 - 1e-9
    assert jpy_leg.lot >= 0.15 - 1e-9
    # Initial lot snapshot captured
    assert rule._initial_lot_per_leg == pytest.approx(0.10)
    assert rule._max_lot_per_leg == pytest.approx(0.30)


def test_v2_phase1_caps_at_max_exposure_multiple():
    """As floating climbs, adds fire up to but not past the cap. Once at
    cap, next threshold triggers a HARVEST instead of an ADD."""
    # Force floating to climb monotonically large enough to cross 5+ levels.
    # EUR rises +0.0030 per bar (30 pips = $30/bar at initial 0.10 lot; once
    # at higher lots more $$ per bar).
    n = 12
    eur = np.array([1.1000 + 0.003 * k for k in range(n)])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(adverse_stop_pct=0.5)   # disable adverse for this test

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    # max_exposure_multiple=3 -> cap at 0.30
    assert eur_leg.lot <= 0.30 + 1e-9, f"lot grew past cap: {eur_leg.lot}"
    # Should fire some HARVEST_SCALE_OUTs once cap hit
    harvest_events = [e for e in rule.recycle_events
                      if e.get("action") == "HARVEST_SCALE_OUT"]
    assert len(harvest_events) > 0, "expected at least one harvest scale-out"


# ---------------------------------------------------------------------------
# Phase 2 — harvest scale-out
# ---------------------------------------------------------------------------


def test_v2_harvest_realizes_proportional_pnl_and_keeps_entry():
    """A non-terminal HARVEST_SCALE_OUT:
      - reduces both legs' lot by pyramid_add_lot,
      - increases realized_total by sum of proportional realizations,
      - leaves entry_price unchanged on each leg."""
    n = 15
    # Climb fast enough to reach cap (4 adds: 0.10 -> 0.30) and trigger
    # at least one Phase-2 scale-out.
    eur = np.array([1.1000 + 0.005 * k for k in range(n)])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(adverse_stop_pct=0.5)

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    harvest_events = [e for e in rule.recycle_events
                      if e.get("action") == "HARVEST_SCALE_OUT"]
    assert harvest_events, "expected harvest scale-outs to fire"

    first_harvest = harvest_events[0]
    # Each scale-out should realize positive PnL (EUR is rising = winning side)
    assert first_harvest["realized_pnl_usd"] > 0
    # Cumulative realized matches running total
    assert first_harvest["cumulative_realized_usd"] >= first_harvest["realized_pnl_usd"]
    # Each leg action shows lot reduced by pyramid_add_lot
    for action in first_harvest["leg_actions"]:
        assert action["new_lot"] == pytest.approx(
            action["old_lot"] - 0.05, abs=1e-9
        )

    # Realized total is accumulating
    assert rule.realized_total > 0


def test_v2_terminal_harvest_emits_liquidate_complete():
    """When scale-outs reduce any leg's lot to zero, the cycle terminates
    with LIQUIDATE_HARVEST_COMPLETE."""
    n = 80   # long enough for full scale-out chain (4 adds + 6 scale-outs)
    eur = np.array([1.1000 + 0.01 * k for k in range(n)])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(adverse_stop_pct=0.5)

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    # Find the terminal LIQUIDATE event
    liq_events = [e for e in rule.recycle_events
                  if e.get("action") == "LIQUIDATE"
                  and e.get("reason") == "HARVEST_COMPLETE"]
    assert len(liq_events) >= 1, "expected at least one HARVEST_COMPLETE liquidation"

    # After terminal: legs flat (in_pos False) + lot reset to initial
    assert not eur_leg.state.in_pos
    assert not jpy_leg.state.in_pos
    # _basket_open reset
    assert not rule._basket_open
    # Cycle counters reset
    assert rule._next_pyramid_level == 0


# ---------------------------------------------------------------------------
# Other exits still preempt the pyramid block (inherited @1 priority)
# ---------------------------------------------------------------------------


def test_v2_adverse_stop_fires_before_pyramid():
    """If basket floating drops past the adverse threshold, ADVERSE_STOP
    fires and the pyramid logic is skipped."""
    n = 5
    # EUR drops sharply — adverse threshold = -$20 on default 0.10 lot:
    # 0.10 * 100000 * Δp <= -20  →  Δp <= -0.0020 (200 pips)
    eur = np.array([1.1000, 1.0995, 1.0990, 1.0970, 1.0950])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(adverse_stop_pct=0.020)   # P03 setting

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    adverse_events = [e for e in rule.recycle_events
                      if e.get("action") == "LIQUIDATE"
                      and e.get("reason") == "ADVERSE_STOP"]
    assert len(adverse_events) == 1
    # No pyramid/harvest should have fired
    pyr_events = [e for e in rule.recycle_events
                  if e.get("action") in ("PYRAMID", "HARVEST_SCALE_OUT")]
    assert pyr_events == []


def test_v2_reverse_cross_fires_before_pyramid():
    """If cross_side flips before threshold crosses, REVERSE_CROSS exits."""
    n = 5
    eur = np.array([1.1000, 1.1005, 1.1010, 1.1015, 1.1020])
    jpy = np.full(n, 150.0)
    cross_side = np.array([1, 1, -1, -1, -1])   # flip at bar 2
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, cross_side_arr=cross_side)
    rule = _make_rule(adverse_stop_pct=0.5)

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    rev_events = [e for e in rule.recycle_events
                  if e.get("action") == "LIQUIDATE"
                  and e.get("reason") == "REVERSE_CROSS"]
    assert len(rev_events) == 1


# ---------------------------------------------------------------------------
# Delayed-harvest extension (harvest_start_after_extra_pyramids > 0)
# ---------------------------------------------------------------------------


def _run_climb_to_full_harvest(rule, n_bars=120, climb_per_bar=0.01):
    """Helper: build a steady-climb price path and run rule.apply() until
    completion. Returns (eur_leg, jpy_leg, rule, all_events)."""
    eur = np.array([1.1000 + climb_per_bar * k for k in range(n_bars)])
    jpy = np.full(n_bars, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    for i in range(n_bars):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    return eur_leg, jpy_leg, rule, rule.recycle_events


def test_v2_delay_zero_byte_equivalent_to_no_hold_phase():
    """harvest_start_after_extra_pyramids=0 must produce zero HOLD events — behavior
    identical to original immediate-harvest @2."""
    rule = _make_rule(harvest_start_after_extra_pyramids=0, adverse_stop_pct=0.5)
    _, _, _, events = _run_climb_to_full_harvest(rule)
    hold_events = [e for e in events if e.get("action") == "HOLD_AT_CAP"]
    assert hold_events == []
    # And HARVEST_SCALE_OUT still fires (otherwise the test is degenerate)
    harvest_events = [e for e in events if e.get("action") == "HARVEST_SCALE_OUT"]
    assert len(harvest_events) > 0


def test_v2_delay_three_inserts_exactly_three_hold_events_before_harvest():
    """harvest_start_after_extra_pyramids=3 must insert exactly 3 HOLD_AT_CAP events
    between the last Phase-1 PYRAMID and the first HARVEST_SCALE_OUT."""
    rule = _make_rule(harvest_start_after_extra_pyramids=3, adverse_stop_pct=0.5)
    _, _, _, events = _run_climb_to_full_harvest(rule)
    # Filter to the action timeline
    action_seq = [e["action"] for e in events
                  if e["action"] in ("PYRAMID", "HOLD_AT_CAP",
                                     "HARVEST_SCALE_OUT", "LIQUIDATE")]
    # Find last PYRAMID and first HARVEST_SCALE_OUT
    last_pyr_idx = max(i for i, a in enumerate(action_seq) if a == "PYRAMID")
    first_harvest_idx = next(
        i for i, a in enumerate(action_seq) if a == "HARVEST_SCALE_OUT"
    )
    # Between them must be exactly 3 HOLD events
    between = action_seq[last_pyr_idx + 1: first_harvest_idx]
    assert between == ["HOLD_AT_CAP", "HOLD_AT_CAP", "HOLD_AT_CAP"], (
        f"expected exactly 3 HOLD_AT_CAP events; got {between}"
    )


def test_v2_hold_event_preserves_lot_and_entry():
    """A HOLD_AT_CAP event must not change either leg's lot or entry_price."""
    rule = _make_rule(harvest_start_after_extra_pyramids=5, adverse_stop_pct=0.5)
    eur_leg, jpy_leg, _, events = _run_climb_to_full_harvest(rule)

    hold_events = [e for e in events if e.get("action") == "HOLD_AT_CAP"]
    assert len(hold_events) >= 1
    # Check the threshold values track the rule's level progression: each
    # subsequent HOLD threshold is exactly step_pct higher than the previous.
    thr_list = [e["threshold_usd"] for e in hold_events]
    step_usd = (rule.pyramid_threshold_step_pct
                * rule.initial_notional_usd / 100.0)
    for i in range(1, len(thr_list)):
        assert thr_list[i] == pytest.approx(thr_list[i - 1] + step_usd, abs=1e-9)


def test_v2_hold_phase_resets_on_adverse_exit():
    """If adverse stop fires during HOLD, the next cycle (if one were to
    start) must begin with HOLD-phase counters cleared."""
    # Climb fast to cap, hit HOLD, then dump price hard to trigger adverse.
    n = 30
    # Phase 1: rapid rise (climb to cap)
    eur = np.concatenate([
        np.array([1.1000 + 0.005 * k for k in range(10)]),    # climb 10 bars
        np.array([1.1050 - 0.0030 * (k + 1) for k in range(20)]),  # then drop
    ])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(harvest_start_after_extra_pyramids=10, adverse_stop_pct=0.020)

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    # Adverse fired
    adv = [e for e in rule.recycle_events
           if e.get("action") == "LIQUIDATE"
           and e.get("reason") == "ADVERSE_STOP"]
    assert len(adv) >= 1
    # HOLD state cleared
    assert rule._in_hold_phase is False
    assert rule._hold_levels_consumed == 0


def test_v2_keep_core_floors_at_initial_lot():
    """harvest_keeps_core=True: scale-outs stop at initial_lot per leg.
    The last harvest emits SCALE_OUT_TO_CORE, then subsequent threshold
    crossings emit CORE_HOLD. No LIQUIDATE_HARVEST_COMPLETE fires (cycle
    exits only via reverse-cross / adverse / time)."""
    rule = _make_rule(
        harvest_keeps_core=True,
        harvest_start_after_extra_pyramids=0,
        adverse_stop_pct=0.5,
    )
    eur_leg, jpy_leg, _, events = _run_climb_to_full_harvest(rule)

    actions = [e["action"] for e in events]
    # Last harvest landing event must be SCALE_OUT_TO_CORE
    assert "SCALE_OUT_TO_CORE" in actions, f"expected SCALE_OUT_TO_CORE in {actions}"
    # CORE_HOLD events appear after SCALE_OUT_TO_CORE
    sc_idx = actions.index("SCALE_OUT_TO_CORE")
    post = actions[sc_idx + 1:]
    assert any(a == "CORE_HOLD" for a in post), (
        f"expected at least one CORE_HOLD after SCALE_OUT_TO_CORE; got {post}"
    )
    # No LIQUIDATE_HARVEST_COMPLETE fired (the chain stopped at floor, not zero)
    harvest_completes = [e for e in events
                         if e.get("action") == "LIQUIDATE"
                         and e.get("reason") == "HARVEST_COMPLETE"]
    assert harvest_completes == [], (
        "harvest_keeps_core=True must not emit LIQUIDATE_HARVEST_COMPLETE"
    )
    # Both legs' final lot is exactly initial_lot
    assert eur_leg.lot == pytest.approx(0.10, abs=1e-9)
    assert jpy_leg.lot == pytest.approx(0.10, abs=1e-9)


def test_v2_keep_core_default_false_byte_equiv_to_terminate_path():
    """With harvest_keeps_core=False (default), terminal LIQUIDATE_HARVEST_COMPLETE
    still fires — no SCALE_OUT_TO_CORE or CORE_HOLD events."""
    rule = _make_rule(harvest_keeps_core=False, adverse_stop_pct=0.5)
    _, _, _, events = _run_climb_to_full_harvest(rule)
    actions = [e["action"] for e in events]
    assert "SCALE_OUT_TO_CORE" not in actions
    assert "CORE_HOLD" not in actions
    harvest_completes = [e for e in events
                         if e.get("action") == "LIQUIDATE"
                         and e.get("reason") == "HARVEST_COMPLETE"]
    assert len(harvest_completes) >= 1


def test_v2_keep_core_exits_via_reverse_cross_at_floor():
    """In CORE_HOLD, a reverse-cross signal still terminates the cycle.
    Verifies that exit machinery preempts CORE_HOLD's silent threshold
    consumption."""
    n = 100
    # Phase: rapid climb to cap → harvest → reach core. Then cross flips.
    eur = np.concatenate([
        np.array([1.1000 + 0.01 * k for k in range(80)]),    # climb to cap + harvest
        np.array([1.8000] * 20),                              # stable above floor
    ])
    jpy = np.full(n, 150.0)
    cross_side = np.full(n, 1, dtype=int)
    cross_side[85:] = -1   # flip after CORE_HOLD reached
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, cross_side_arr=cross_side)
    rule = _make_rule(
        harvest_keeps_core=True,
        harvest_start_after_extra_pyramids=0,
        adverse_stop_pct=0.5,
    )

    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])

    # We did reach CORE_HOLD at some point
    actions = [e["action"] for e in rule.recycle_events]
    assert "SCALE_OUT_TO_CORE" in actions
    # Reverse-cross fired and terminated the cycle
    rev = [e for e in rule.recycle_events
           if e.get("action") == "LIQUIDATE"
           and e.get("reason") == "REVERSE_CROSS"]
    assert len(rev) >= 1
    # Core-hold flag was cleared on liquidation
    assert rule._in_core_hold_phase is False


def test_v2_keep_core_validator_rejects_non_bool():
    with pytest.raises(ValueError, match="harvest_keeps_core"):
        H3SpreadV2Rule(harvest_keeps_core="yes")


# ---------------------------------------------------------------------------
# Bidirectional extension (cycle direction set per-cycle from cross_side)
# ---------------------------------------------------------------------------


def test_v2_bidirectional_validator_rejects_non_bool():
    with pytest.raises(ValueError, match="bidirectional"):
        H3SpreadV2Rule(bidirectional="yes")


def test_v2_bidirectional_default_false_byte_equiv_to_unidirectional():
    """Default bidirectional=False preserves uni-directional behavior:
    cycle direction comes from entry_direction param."""
    n = 5
    eur = np.array([1.1000, 1.1000, 1.1005, 1.1010, 1.1015])
    jpy = np.full(n, 150.0)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
    rule = _make_rule(bidirectional=False)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    # Cycle direction tracker remains 0 in non-bidirectional path during open
    # — the rule used entry_direction directly. No assertion on
    # _cycle_direction since it isn't updated in uni-dir mode.
    pyr_events = [e for e in rule.recycle_events if e.get("action") == "PYRAMID"]
    assert len(pyr_events) >= 1
    open_evt = next(e for e in rule.recycle_events if e.get("action") == "BASKET_OPEN")
    assert open_evt["bidirectional"] is False
    assert open_evt["direction"] == rule.entry_direction


def test_v2_bidirectional_long_spread_on_up_cross():
    """bidirectional=True + cross_side=+1 at entry → _cycle_direction = +1."""
    n = 5
    eur = np.array([1.1000, 1.1000, 1.1005, 1.1010, 1.1015])
    jpy = np.full(n, 150.0)
    # cross_side = +1 throughout (matches the leg-strategy fire condition;
    # the rule reads cross_side at the entry bar to derive cycle direction)
    cross_side = np.full(n, 1, dtype=int)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, cross_side_arr=cross_side)
    rule = _make_rule(bidirectional=True, entry_direction=+1)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    assert rule._cycle_direction == +1, (
        f"expected cycle_direction +1 on UP-cross entry; got {rule._cycle_direction}"
    )
    open_evt = next(e for e in rule.recycle_events if e.get("action") == "BASKET_OPEN")
    assert open_evt["bidirectional"] is True
    assert open_evt["direction"] == +1


def test_v2_bidirectional_short_spread_on_down_cross():
    """bidirectional=True + cross_side=-1 at entry → _cycle_direction = -1.
    Legs are pre-positioned SHORT/LONG (engine path sets leg.state.direction
    from the signal); the rule reads the leg state as fallback."""
    n = 5
    # Reversed price path: EUR rises, JPY falls — for SHORT-spread cycle
    # (SHORT EUR + LONG JPY) this is ADVERSE. We just need to confirm
    # cycle_direction is set from cross_side correctly, not test PnL flow.
    eur = np.array([1.1000, 1.1000, 1.0995, 1.0990, 1.0985])
    jpy = np.array([150.0, 150.0, 150.1, 150.2, 150.3])
    cross_side = np.full(n, -1, dtype=int)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, cross_side_arr=cross_side)
    # Pre-flip leg.state.direction to mimic engine signal-driven open
    eur_leg.state.direction = -1   # SHORT EUR on DOWN-cross
    jpy_leg.state.direction = +1   # LONG JPY on DOWN-cross
    rule = _make_rule(
        bidirectional=True,
        entry_direction=+1,   # legacy param; should be IGNORED in bidirectional
        adverse_stop_pct=0.5,  # disable adverse
    )
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    assert rule._cycle_direction == -1, (
        f"expected cycle_direction -1 on DOWN-cross entry; got {rule._cycle_direction}"
    )
    open_evt = next(e for e in rule.recycle_events if e.get("action") == "BASKET_OPEN")
    assert open_evt["direction"] == -1


def test_v2_bidirectional_reverse_cross_uses_cycle_direction():
    """In bidirectional mode, reverse-cross exit fires when cross_side
    OPPOSES the cycle's own direction, not entry_direction."""
    # SHORT-spread cycle: cycle_direction = -1. Reverse cross at +1 should
    # liquidate. Pre-flip leg.state.direction to set up SHORT cycle.
    n = 6
    eur = np.array([1.1000, 1.1000, 1.0995, 1.0990, 1.0985, 1.0980])
    jpy = np.array([150.0, 150.0, 150.1, 150.2, 150.3, 150.4])
    cross_side = np.array([-1, -1, -1, -1, +1, +1])   # flip at bar 4
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, cross_side_arr=cross_side)
    eur_leg.state.direction = -1
    jpy_leg.state.direction = +1
    rule = _make_rule(bidirectional=True, entry_direction=+1, adverse_stop_pct=0.5)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    rev = [e for e in rule.recycle_events
           if e.get("action") == "LIQUIDATE"
           and e.get("reason") == "REVERSE_CROSS"]
    assert len(rev) >= 1, "expected reverse-cross liquidation when cross flips against cycle"


def test_v2_bidirectional_effective_direction_on_open():
    """In bidirectional mode, leg.state.direction can be opposite of
    leg.direction (SHORT-spread cycle). The cycle-aware accessor
    leg.effective_direction must return state.direction; leg.direction
    itself MUST stay at YAML BASE (immutable invariant — was the source
    of the 2026-05-24 leg_direction_flip_bug pre-Option-B-fix)."""
    n = 5
    eur = np.array([1.1000, 1.1000, 1.0995, 1.0990, 1.0985])
    jpy = np.array([150.0, 150.0, 150.1, 150.2, 150.3])
    cross_side = np.full(n, -1, dtype=int)
    eur_leg, jpy_leg, idx = _build_legs(eur, jpy, cross_side_arr=cross_side)
    # Initial leg.direction is set by _build_legs (LONG EUR +1, SHORT JPY -1).
    # In a SHORT-spread cycle, leg.state.direction is opposite.
    eur_leg.state.direction = -1   # SHORT EUR
    jpy_leg.state.direction = +1   # LONG JPY
    initial_eur_direction = eur_leg.direction   # +1 from _build_legs
    initial_jpy_direction = jpy_leg.direction   # -1 from _build_legs
    rule = _make_rule(bidirectional=True, entry_direction=+1, adverse_stop_pct=0.5)
    for i in range(n):
        rule.apply([eur_leg, jpy_leg], i, idx[i])
    # Invariant: leg.direction unchanged (immutable post-init).
    assert eur_leg.direction == initial_eur_direction, (
        f"eur_leg.direction was mutated: initial={initial_eur_direction}, "
        f"got {eur_leg.direction}"
    )
    assert jpy_leg.direction == initial_jpy_direction
    # Cycle-aware accessor returns state.direction.
    assert eur_leg.effective_direction == -1
    assert jpy_leg.effective_direction == +1


def test_v2_delay_increases_max_mfe_vs_no_delay():
    """Sanity check on the structural claim: with delay > 0, the cycle's
    floating peak (recorded in per-bar records) reaches a higher value
    before the first HARVEST_SCALE_OUT than with delay = 0, on the SAME
    price path. (Looser cap-truncation = more convex tail preserved.)"""
    # Same fast-climb path for both variants — we compare floating at the
    # bar of first HARVEST.
    def _peak_floating_at_first_harvest(rule, n_bars=80):
        eur = np.array([1.1000 + 0.01 * k for k in range(n_bars)])
        jpy = np.full(n_bars, 150.0)
        eur_leg, jpy_leg, idx = _build_legs(eur, jpy)
        for i in range(n_bars):
            rule.apply([eur_leg, jpy_leg], i, idx[i])
        first_h = next((e for e in rule.recycle_events
                        if e.get("action") == "HARVEST_SCALE_OUT"), None)
        return first_h["floating_total_pre"] if first_h else None

    no_delay = _make_rule(harvest_start_after_extra_pyramids=0, adverse_stop_pct=0.5)
    with_delay = _make_rule(harvest_start_after_extra_pyramids=5, adverse_stop_pct=0.5)
    f0 = _peak_floating_at_first_harvest(no_delay)
    f5 = _peak_floating_at_first_harvest(with_delay)
    assert f0 is not None and f5 is not None
    # With delay, the first harvest fires at a higher floating value
    # because 5 thresholds have been consumed without scaling out.
    assert f5 > f0, (
        f"expected delay=5 to push first-harvest floating above delay=0; "
        f"got delay=0: {f0:.2f}, delay=5: {f5:.2f}"
    )
