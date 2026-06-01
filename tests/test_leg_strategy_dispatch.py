"""Tests for the recycle-rule -> leg-strategy dispatch in run_pipeline.

R1 invariant guard (2026-06-01):
  Every recycle rule registered in `governance/recycle_rules/registry.yaml`
  MUST be in EXACTLY ONE of:
    - LEG_STRATEGY_DISPATCH  (proposal-based legs; fire entry signals)
    - CONTINUOUS_HOLD_RULES  (always-open legs; rule manages cycle)

  A registered rule absent from BOTH silently falls through to
  ContinuousHoldStrategy at runtime, producing degraded behavior that
  LOOKS like a normal run. ZBND 2026-06-01 incident: 24 episodes ran in
  this degraded mode before root-cause was found. These tests prevent
  recurrence at test time; `LegDispatchError` prevents it at runtime.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.run_pipeline import (
    CONTINUOUS_HOLD_RULES,
    LEG_STRATEGY_DISPATCH,
    LegDispatchError,
    _dispatch_leg_strategies,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = PROJECT_ROOT / "governance" / "recycle_rules" / "registry.yaml"


def _registered_rule_names() -> set[str]:
    """All recycle rule names declared in governance/recycle_rules/registry.yaml."""
    with open(REGISTRY, "r", encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    return {entry["name"] for entry in registry.get("rules", [])}


def _two_leg_directive(sym_a: str, sym_b: str) -> dict:
    return {
        "basket": {
            "legs": [
                {"symbol": sym_a, "direction": "long"},
                {"symbol": sym_b, "direction": "short"},
            ]
        }
    }


# ──────────────────────────────────────────────────────────────────────────
# Invariant tests — the actual R1 guard
# ──────────────────────────────────────────────────────────────────────────

def test_every_registered_rule_has_a_leg_strategy_assignment():
    """Registry-vs-dispatch coverage. The 2026-06-01 ZBND incident root
    cause was a registered rule with no assignment here."""
    registered = _registered_rule_names()
    assigned = set(LEG_STRATEGY_DISPATCH) | CONTINUOUS_HOLD_RULES
    missing = registered - assigned
    assert not missing, (
        f"Recycle rules registered in {REGISTRY.relative_to(PROJECT_ROOT)} "
        f"but with no leg-strategy assignment: {sorted(missing)}. "
        f"Add each to LEG_STRATEGY_DISPATCH (proposal-based) or "
        f"CONTINUOUS_HOLD_RULES (always-open) in tools/run_pipeline.py."
    )


def test_dispatch_and_continuous_hold_are_disjoint():
    """A rule must be in EXACTLY one collection — the dispatcher can't
    safely use both a proposal-based leg strategy AND the continuous-hold
    default."""
    overlap = set(LEG_STRATEGY_DISPATCH) & CONTINUOUS_HOLD_RULES
    assert not overlap, (
        f"Rules in both LEG_STRATEGY_DISPATCH and CONTINUOUS_HOLD_RULES: "
        f"{sorted(overlap)}. Pick exactly one."
    )


def test_unknown_rule_name_raises_legdispatcherror():
    """Unregistered rule names MUST raise — never silently fall through."""
    parsed = _two_leg_directive("EURUSD", "GBPUSD")
    rule_block = {"name": "fictional_rule_that_does_not_exist", "params": {}}
    with pytest.raises(LegDispatchError, match="fictional_rule"):
        _dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)


def test_empty_rule_name_falls_back_to_continuous_hold():
    """Non-basket directives may arrive with no rule name; keep legacy
    continuous-hold behavior for those (basket detection is upstream)."""
    from tools.recycle_strategies import ContinuousHoldStrategy
    parsed = _two_leg_directive("EURUSD", "GBPUSD")
    leg_strategies = _dispatch_leg_strategies(parsed, {}, bar_seconds=900)
    for sym, strategy in leg_strategies.items():
        assert isinstance(strategy, ContinuousHoldStrategy), (
            f"Empty rule_name should yield ContinuousHoldStrategy for {sym}, "
            f"got {type(strategy).__name__}."
        )


# ──────────────────────────────────────────────────────────────────────────
# Regression guards — specific failure cases from past incidents
# ──────────────────────────────────────────────────────────────────────────

def test_zband_dispatches_to_pine_zrev_leg_strategy():
    """ZBND 2026-06-01 regression: pine_ratio_zrev_v1_zband MUST dispatch
    to PineZRevLegStrategy. The original incident was this exact name
    silently dispatching to ContinuousHoldStrategy."""
    from tools.recycle_strategies import PineZRevLegStrategy
    parsed = _two_leg_directive("AUDJPY", "AUDNZD")
    rule_block = {"name": "pine_ratio_zrev_v1_zband", "params": {}}
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)
    assert len(leg_strategies) == 2
    for sym, strategy in leg_strategies.items():
        assert isinstance(strategy, PineZRevLegStrategy), (
            f"ZBND silent-fallthrough regression: {sym} got "
            f"{type(strategy).__name__}, expected PineZRevLegStrategy."
        )


def test_pine_zrev_v1_dispatches_to_pine_zrev_leg_strategy():
    from tools.recycle_strategies import PineZRevLegStrategy
    parsed = _two_leg_directive("EURUSD", "GBPUSD")
    rule_block = {"name": "pine_ratio_zrev_v1", "params": {}}
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)
    for strategy in leg_strategies.values():
        assert isinstance(strategy, PineZRevLegStrategy)


def test_pine_zrev_v1_zcross_dispatches_to_pine_zrev_leg_strategy():
    from tools.recycle_strategies import PineZRevLegStrategy
    parsed = _two_leg_directive("EURUSD", "GBPUSD")
    rule_block = {"name": "pine_ratio_zrev_v1_zcross", "params": {}}
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)
    for strategy in leg_strategies.values():
        assert isinstance(strategy, PineZRevLegStrategy)


def test_pine_zrev_shared_armed_state_is_one_instance_per_basket():
    """Both legs of a basket MUST share the same PineZRevArmedState
    instance — the proposal+approval handshake is keyed on it."""
    parsed = _two_leg_directive("AUDJPY", "AUDNZD")
    rule_block = {"name": "pine_ratio_zrev_v1_zband", "params": {}}
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)
    states = [s.armed_state for s in leg_strategies.values()]
    assert states[0] is states[1], (
        "Both basket legs must share the SAME armed_state instance; "
        "without it, propose/approve atomicity breaks."
    )


def test_cointegration_meanrev_dispatches_to_coint_trigger_leg_strategy():
    from tools.recycle_strategies import CointTriggerLegStrategy
    parsed = _two_leg_directive("EURUSD", "USDJPY")
    rule_block = {"name": "cointegration_meanrev_v1_2", "params": {}}
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=900)
    for strategy in leg_strategies.values():
        assert isinstance(strategy, CointTriggerLegStrategy)


def test_h3_spread_dispatches_to_spread_cross_leg_strategy():
    from tools.recycle_strategies import SpreadCrossLegStrategy
    parsed = _two_leg_directive("EURUSD", "USDJPY")
    rule_block = {
        "name": "H3_spread",
        "params": {"entry_direction": 1, "entry_delay_bars": 12},
    }
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=300)
    for strategy in leg_strategies.values():
        assert isinstance(strategy, SpreadCrossLegStrategy)


def test_h2_recycle_dispatches_to_continuous_hold():
    from tools.recycle_strategies import ContinuousHoldStrategy
    parsed = _two_leg_directive("EURUSD", "USDJPY")
    rule_block = {"name": "H2_recycle", "params": {}}
    leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds=300)
    for strategy in leg_strategies.values():
        assert isinstance(strategy, ContinuousHoldStrategy)
