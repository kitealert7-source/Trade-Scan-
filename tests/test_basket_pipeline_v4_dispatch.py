"""Tests for basket_pipeline._instantiate_rule H2_recycle@4 dispatch (Phase D).

Locks in the wiring: when a directive specifies H2_recycle@4, the pipeline:
  - instantiates H2RecycleRuleV4 (not @1/@2/@3)
  - threads all v1 params with correct defaults
  - threads new v4 params (switch_n, retrace_pct) with defaults 5 / 0.30
  - threads identity kwargs (run_id / directive_id / basket_id)
  - leaves basket_runner unset (filled by BasketRunner.__init__'s back-ref)
"""
from __future__ import annotations

import pytest

from tools.basket_pipeline import _instantiate_rule
from tools.recycle_rules import (
    H2RecycleRule, H2RecycleRuleV2, H2RecycleRuleV3, H2RecycleRuleV4,
)


# ---------------------------------------------------------------------------
# Dispatch: name + version -> correct class
# ---------------------------------------------------------------------------


def test_dispatch_h2_recycle_v4_returns_v4_instance():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4, "params": {}},
        run_id="r1", directive_id="d1", basket_id="H2",
    )
    assert isinstance(rule, H2RecycleRuleV4)
    # H2RecycleRuleV4 inherits from H2RecycleRule but the dispatch must return
    # the subclass, not the base, so behavior matches the v4 mechanic.
    assert type(rule) is H2RecycleRuleV4


def test_dispatch_h2_recycle_v1_still_returns_v1_not_v4():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 1, "params": {}},
        run_id="r1", directive_id="d1", basket_id="H2",
    )
    assert type(rule) is H2RecycleRule
    assert not isinstance(rule, H2RecycleRuleV4)


def test_dispatch_h2_recycle_v2_still_returns_v2():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 2, "params": {}},
    )
    assert type(rule) is H2RecycleRuleV2


def test_dispatch_h2_recycle_v3_still_returns_v3():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 3, "params": {}},
        run_id="r1", directive_id="d1", basket_id="H2",
    )
    assert type(rule) is H2RecycleRuleV3


# ---------------------------------------------------------------------------
# Default param threading for v4
# ---------------------------------------------------------------------------


def test_v4_defaults_match_registry():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4, "params": {}},
    )
    assert rule.switch_n == 5
    assert rule.retrace_pct == 0.30
    assert rule.trigger_usd == 10.0
    assert rule.add_lot == 0.01
    assert rule.starting_equity == 1000.0
    assert rule.harvest_target_usd == 2000.0
    assert rule.dd_freeze_frac == 0.10
    assert rule.margin_freeze_frac == 0.15
    assert rule.leverage == 1000.0
    assert rule.factor_column == "compression_5d"
    assert rule.factor_min == 5.0  # Phase-2 default (different from @1's 10.0)
    assert rule.factor_operator == ">="


def test_v4_override_switch_n():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4,
         "params": {"switch_n": 7}},
    )
    assert rule.switch_n == 7


def test_v4_override_retrace_pct():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4,
         "params": {"retrace_pct": 0.50}},
    )
    assert rule.retrace_pct == 0.50


def test_v4_override_v1_params():
    """v1 params should still be overrideable on v4 (inherited)."""
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4,
         "params": {
             "trigger_usd": 25.0,
             "factor_min": 8.0,
             "factor_operator": "<=",
             "harvest_target_usd": 3000.0,
         }},
    )
    assert rule.trigger_usd == 25.0
    assert rule.factor_min == 8.0
    assert rule.factor_operator == "<="
    assert rule.harvest_target_usd == 3000.0


# ---------------------------------------------------------------------------
# Identity kwargs threaded into v4
# ---------------------------------------------------------------------------


def test_v4_threads_identity_kwargs():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4, "params": {}},
        run_id="run_abc123",
        directive_id="90_PORT_H2_5M_RECYCLE_S14_V1_P00",
        basket_id="H2",
    )
    assert rule.run_id == "run_abc123"
    assert rule.directive_id == "90_PORT_H2_5M_RECYCLE_S14_V1_P00"
    assert rule.basket_id == "H2"


# ---------------------------------------------------------------------------
# basket_runner back-ref defaults to None at instantiation
# ---------------------------------------------------------------------------


def test_v4_basket_runner_unset_at_instantiation():
    """basket_pipeline does NOT pre-populate basket_runner; that's the runner's
    job at attach time (via BasketRunner.__init__'s injection)."""
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4, "params": {}},
    )
    assert rule.basket_runner is None


# ---------------------------------------------------------------------------
# factor_column override + factor_min validation passes through
# ---------------------------------------------------------------------------


def test_v4_factor_column_override_via_kwarg():
    """When basket_pipeline calls _instantiate_rule with factor_column=...
    (overriding any directive params value), it wins."""
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 4,
         "params": {"factor_column": "stretch_z20", "factor_operator": "abs_<="}},
        factor_column="stretch_z20",
    )
    assert rule.factor_column == "stretch_z20"
    assert rule.factor_operator == "abs_<="


# ---------------------------------------------------------------------------
# Invalid params surface validation errors at instantiation
# ---------------------------------------------------------------------------


def test_v4_invalid_switch_n_raises():
    with pytest.raises(ValueError, match="switch_n"):
        _instantiate_rule(
            {"name": "H2_recycle", "version": 4,
             "params": {"switch_n": 0}},
        )


def test_v4_invalid_retrace_pct_raises():
    with pytest.raises(ValueError, match="retrace_pct"):
        _instantiate_rule(
            {"name": "H2_recycle", "version": 4,
             "params": {"retrace_pct": 1.0}},
        )


def test_v4_invalid_factor_operator_raises():
    with pytest.raises(ValueError, match="factor_operator"):
        _instantiate_rule(
            {"name": "H2_recycle", "version": 4,
             "params": {"factor_operator": "=="}},
        )
